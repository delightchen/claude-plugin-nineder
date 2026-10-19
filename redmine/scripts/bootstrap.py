#!/usr/bin/env python3
"""redmine plugin 4.1.0 —— SessionStart bootstrap 本體（分發模型 v2）

這是 bootstrap.sh 的純 Python 版本，4.1.0 起兩者並存：bootstrap.sh 在 POSIX
（macOS／Linux／WSL）上仍是唯一的呼叫入口（settings.json 與 /redmine:setup 都指向
它），但它現在只是一支轉接殼，唯一動作是 exec 這支 bootstrap.py；所有實際邏輯都在
這裡，用 os.path／json／subprocess，不含任何殼層語法，Windows／macOS／Linux 通用。

*為什麼要拆*：原本 bootstrap.sh 除了「寫 settings.json」那一段是內嵌 python3
heredoc，其餘（複製檔案、種 seed、清舊指標檔）都是純 bash，在原生 Windows 上完全
執行不了（沒有 bash）。拆出來之後，同一份邏輯在原生 Windows 上也能用
`python3 bootstrap.py`（或任何解得到這支檔案的方式）直接跑。

*目前驗證範圍*：邏輯本身在這台 macOS 機器上驗證過語法與冪等性（同一支腳本重跑兩次
行為一致），但 *尚未在真實 Windows 機器上跑過*——`/redmine:setup` 指令本身、
`bootstrap.sh`、`issue_context.sh`、`nineder-skill` 的 `sync.sh` 都還是純 bash，
原生 Windows 上目前仍然只有這支 bootstrap.py 能跑；換句話說：Windows 機器裝了這個
plugin *還是需要先手動找一種方式執行一次這支檔案*（例如直接 `python3
<路徑>\\bootstrap.py`），才會寫入下面第三步的 hook。這件事一旦有 Windows
機器可以實測，才能確定第三步寫進去的 hook 指令是不是真的在該平台上會被正確執行
（例如 Claude Code Desktop／CLI 在 Windows 上執行 hook 指令時用的是哪一種殼層、
`sys.executable` 這條路徑會不會含空白等，都還沒有實機驗證過）。

plugin 在 v2 之後只剩這一支入口，做六件事，順序固定：
  0. 版本自報：印出目前 plugin.json 的 version／versionDate，不管其餘五步有沒有變動都印
     （4.0.9 新增）
  1. 把 hook 需要的腳本複製到 ~/.claude/nineder/bin/（穩定位置）—— 理由見 STABLE_BIN
  2. seed：~/.claude/skills/nineder-skill/ 不存在就從 plugin 的 seed/ 種下去（存在就完全
     不碰，之後由 Redmine 附檔自我升版——plugin 永遠不覆寫已安裝的版本）
  3. settings：冪等維護 ~/.claude/settings.json 的 UserPromptSubmit、SessionStart，
     PreToolUse 的 create_issue／update_issue／update_issue_note 自動夾帳、create_issue_reminder 自動補回程連結，以及 SessionStart 的每日
     用量排程、PostToolUse 的議題轉 Resolved 排程（4.1.0 起 hook 指令一律用本檔案
     旁邊的 run_if_exists.py 當轉接殼，不再依賴任何殼層變數展開或條件判斷語法——
     這是這一版讓排程理論上可以在 Windows 上運作的關鍵改動，見下方 build_hooks_want()）
  4. 清舊：移除 v3.x 的 ~/.claude/commands/ 指標檔——它們指向 plugin 內已不存在的 skill
  5. sync：呼叫 ~/.claude/skills/nineder-skill/scripts/sync.sh --auto（*仍是 POSIX
     限定*——sync.sh 本體也是 bash 包一段 python3 heredoc，還沒有跟這次一起拆成
     純 Python；Windows 上這一步會被跳過並印一行說明，不影響前面四步）

三條不可放寬的界線：
  * 不碰 ~/.claude.json —— 那是 Claude Code 頻繁寫入的主設定檔，SessionStart 併發寫有風險；
    MCP 註冊（claude mcp add）交給 /nineder-skill 在對話裡做
  * 不覆寫已安裝的 skill —— seed 只在目錄不存在時動作
  * fail-open —— 任何錯誤都以 exit 0 收尾，絕不阻擋 session 開始
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IS_WINDOWS = os.name == "nt"

HOME = Path(os.path.expanduser("~"))
SKILLS_DIR = HOME / ".claude" / "skills"
SELF_SKILL = SKILLS_DIR / "nineder-skill"
STABLE_BIN = HOME / ".claude" / "nineder" / "bin"
SETTINGS_PATH = HOME / ".claude" / "settings.json"

def _redmine_plugin_version(root: Path) -> tuple[int, ...] | None:
    try:
        d = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        if d.get("name") != "redmine" or not (root / "scripts" / "bootstrap.sh").exists():
            return None
        return tuple(int(x) for x in str(d.get("version", "")).split("."))
    except Exception:
        return None


def _candidate_plugin_roots() -> list[Path]:
    # 桌面版組織派發的目錄含 session id；Windows 那條（%APPDATA%\Claude）尚未實機確認。
    desktop_bases = [HOME / "Library" / "Application Support" / "Claude"]
    if os.environ.get("APPDATA"):
        desktop_bases.append(Path(os.environ["APPDATA"]) / "Claude")
    roots: list[Path] = []
    for base in desktop_bases:
        roots += base.glob("local-agent-mode-sessions/*/*/rpm/*")
    plugins = HOME / ".claude" / "plugins"
    roots.append(plugins / "marketplaces" / "nineder" / "redmine")
    roots += (plugins / "cache" / "nineder" / "redmine").glob("*")
    return roots


def resolve_plugin_root() -> Path:
    """取本機所有 redmine plugin 目錄中版本最高的一份（#27320）。

    從 settings.json 的 SessionStart 執行時，這支檔案在 ~/.claude/nineder/bin/，
    上一層沒有 scripts/，而桌面版不執行 plugin 自己的 hook，CLAUDE_PLUGIN_ROOT
    永遠不會被設定——不主動去找，bin/ 就永遠不會更新。反過來 CLAUDE_PLUGIN_ROOT
    可能指向很久沒更新的 CLI cache，也不能無條件相信它，否則會把 bin/ 蓋回舊版。
    """
    own = Path(__file__).resolve().parent.parent
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    first = [Path(env)] if env else []
    best: tuple[tuple[int, ...], Path] | None = None
    try:
        candidates = first + [own] + _candidate_plugin_roots()
    except Exception:
        candidates = first + [own]
    for root in candidates:
        v = _redmine_plugin_version(root)
        if v is not None and (best is None or v > best[0]):
            best = (v, root)
    if best:
        return best[1]
    return first[0] if first else own


PLUGIN_ROOT = resolve_plugin_root()

# 複製到 ~/.claude/nineder/bin/ 的完整清單。bootstrap.py 自己也在清單裡——
# SessionStart 的自我重呼叫一律指向這份穩定副本，不指向 plugin 目錄（後者含
# session id，每次開對話都會變，見「兩條派發來源」）。.sh 兩支在原生 Windows
# 上複製過去也沒有意義（沒有殼層可以跑），但複製本身無害，先原樣帶著，等
# issue_context.sh／sync.sh 哪天也拆成純 Python 版本時不必再補這一段。
STABLE_BIN_FILES = [
    "bootstrap.py",
    "bootstrap.sh",
    "issue_context.sh",
    "run_if_exists.py",
    "ai_usage_inline.py",
    "session_link_inline.py",
    "collect.py",
    "daily_trigger.py",
    "resolved_trigger.py",
]


def say(line: str) -> None:
    print(line, flush=True)


def step0_version_banner() -> None:
    plugin_json = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    try:
        with open(plugin_json, encoding="utf-8") as f:
            d = json.load(f)
        ver = d.get("version", "?")
        date = d.get("versionDate", "版號日期未標")
        say(f"nineder-skill：目前 Redmine plugin 版本 v{ver}（{date}）")
    except Exception:
        pass


def _files_identical(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def step1_copy_stable_bin() -> None:
    src_dir = PLUGIN_ROOT / "scripts"
    if not (src_dir / "bootstrap.sh").exists() or not (src_dir / "issue_context.sh").exists():
        return
    try:
        STABLE_BIN.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    copied = 0
    for name in STABLE_BIN_FILES:
        src = src_dir / name
        dst = STABLE_BIN / name
        if not src.exists():
            continue
        if dst.exists() and _files_identical(src, dst):
            continue
        try:
            shutil.copy2(src, dst)
            try:
                dst.chmod(dst.stat().st_mode | 0o111)
            except OSError:
                pass  # Windows 的可執行位元語意不同，chmod 失敗不影響後續使用
            copied += 1
        except OSError:
            continue

    if copied:
        say(f"nineder-skill：已更新 {copied} 支開機腳本到 ~/.claude/nineder/bin/")


def step2_seed_nineder_skill() -> None:
    if SELF_SKILL.exists():
        return
    seed = PLUGIN_ROOT / "seed" / "nineder-skill"
    if seed.is_dir():
        try:
            SKILLS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copytree(seed, SELF_SKILL)
            sync_sh = SELF_SKILL / "scripts" / "sync.sh"
            if sync_sh.exists():
                try:
                    sync_sh.chmod(sync_sh.stat().st_mode | 0o111)
                except OSError:
                    pass
            say("nineder-skill：已在這台機器種下同步器（種子版）。輸入 /nineder-skill 完成設定。")
        except OSError:
            pass
    else:
        # 從穩定位置被 hook 呼叫時看不到 plugin 的 seed —— 這是預期，不是錯誤。種子只在
        # 第一次需要，而第一次一定由 /redmine:setup（帶得到 plugin 路徑）觸發。
        say("nineder-skill：同步器尚未安裝。請在對話中輸入 /redmine:setup 完成首次設定。")


def build_hooks_want() -> tuple[
    list[tuple[str, str]],
    list[tuple[str, str, str]],
    dict[str, str],
    dict[str, str],
]:
    """組出這次要寫進 settings.json 的 hook 清單。

    4.1.0 起，所有 .py 目標一律透過 run_if_exists.py 這支轉接殼呼叫：
    指令是三個都帶引號的路徑（直譯器、轉接殼、目標腳本），不含任何殼層變數
    展開（$HOME、%USERPROFILE% 之類）或條件判斷語法（[ -x ] 、 && 、 exec）——
    這樣同一條指令字串理論上不論被哪一種殼層執行都能動作。轉接殼本身找不到
    目標檔案就靜默結束（exit 0），維持既有的 fail-open 設計。

    .sh 目標（issue_context.sh）沒有對應的 Windows 執行方式，仍用舊式的
    bash 條件指令，且只在非 Windows 平台寫入——原生 Windows 上完全不寫這條，
    而不是寫一條保證失敗的指令。
    """
    py = sys.executable
    launcher = STABLE_BIN / "run_if_exists.py"

    def py_cmd(script: str) -> str:
        target = STABLE_BIN / script
        return f'"{py}" "{launcher}" "{target}"'

    want: list[tuple[str, str]] = [
        ("SessionStart", "bootstrap.py"),
        ("SessionStart", "daily_trigger.py"),
    ]
    want_cmds = {script: py_cmd(script) for _, script in want}

    if not IS_WINDOWS:
        script = "issue_context.sh"
        target = STABLE_BIN / script
        want.append(("UserPromptSubmit", script))
        want_cmds[script] = f'SCRIPT="{target}"; [ -x "$SCRIPT" ] && exec "$SCRIPT"; exit 0'

    want_matched: list[tuple[str, str, str]] = [
        ("PreToolUse", "mcp__nineder-redmine__create_issue", "ai_usage_inline.py"),
        ("PreToolUse", "mcp__nineder-redmine__update_issue", "ai_usage_inline.py"),
        # 修改既有 note（#27641）：同一支 hook，伺服器把夾帶的用量記成一列「修改記錄」，
        # 不碰原 journal 那一列。需要 collect.py 認得這支工具（4.1.19 起），否則修改成功後
        # 那段用量會被當成原 journal 的用量去送——所以 matcher 與 collect.py 同版出貨。
        ("PreToolUse", "mcp__nineder-redmine__update_issue_note", "ai_usage_inline.py"),
        # 建排程提醒（#27754）：自動把「回到這個 session」的連結補進 note。連結需要的兩個編號只存在
        # 本機 App 的中繼檔，Redmine 的 MCP 看不到；與夾帶用量同一個道理，從模型自律搬到 hook 上。
        ("PreToolUse", "mcp__nineder-redmine__create_issue_reminder", "session_link_inline.py"),
        ("PostToolUse", "mcp__nineder-redmine__update_issue", "resolved_trigger.py"),
    ]
    want_matched_cmds = {script: py_cmd(script) for _, _, script in want_matched}

    return want, want_matched, want_cmds, want_matched_cmds


# 4.1.0 把 SessionStart 的自我重呼叫從 bootstrap.sh 換成 bootstrap.py（理由見
# build_hooks_want 的說明）。舊機器 settings.json 裡指向 bootstrap.sh 的那條不會出現
# 在新的 WANT 清單裡，單靠「for event, script in want」那個迴圈不會被清掉，會變成
# 孤兒條目跟新條目並存、每次 SessionStart 都多跑一次——4.1.0 開發期間用一份模擬舊
# settings.json 實測抓到這個殘留，這裡是專門處理「改名但不留孤兒」的清單。
RETIRED_HOOK_SCRIPTS: list[tuple[str, str]] = [
    ("SessionStart", "bootstrap.sh"),
]


def step3_settings_hooks() -> None:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    except Exception:
        return  # 讀不到或壞損：完全不碰

    want, want_matched, want_cmds, want_matched_cmds = build_hooks_want()

    hooks = data.setdefault("hooks", {})
    changed = False

    for event, script in RETIRED_HOOK_SCRIPTS:
        markers = (
            os.path.join("nineder", "bin", script),
            "marketplaces/nineder/redmine/scripts/" + script,
        )
        entries = hooks.get(event) or []
        kept = [e for e in entries if not any(m in json.dumps(e) for m in markers)]
        if kept != entries:
            hooks[event] = kept
            changed = True

    for event, script in want:
        # 認得舊版寫進去的條目也要能清掉：4.1.0 之前的絕對路徑用 os.sep 組出來的
        # marker（POSIX 是 "nineder/bin/腳本"，Windows 是 "nineder\bin\腳本"），
        # 4.0.3 以前寫死的 CLI marketplace 路徑一併算進去，一律換成新的那一條。
        markers = (
            os.path.join("nineder", "bin", script),
            "marketplaces/nineder/redmine/scripts/" + script,
        )
        cmd = want_cmds[script]
        entries = hooks.get(event) or []
        ours = {"hooks": [{"type": "command", "command": cmd}]}
        kept = [e for e in entries if not any(m in json.dumps(e) for m in markers)]
        wanted = kept + [ours]
        if wanted != entries:
            hooks[event] = wanted
            changed = True

    for event, matcher, script in want_matched:
        cmd = want_matched_cmds[script]
        markers = (os.path.join("nineder", "bin", script),)
        entries = hooks.get(event) or []
        ours = {"matcher": matcher, "hooks": [{"type": "command", "command": cmd}]}
        kept = [
            e
            for e in entries
            if not (e.get("matcher") == matcher and any(m in json.dumps(e) for m in markers))
        ]
        wanted = kept + [ours]
        if wanted != entries:
            hooks[event] = wanted
            changed = True

    if not changed:
        return

    fd, tmp = tempfile.mkstemp(dir=str(SETTINGS_PATH.parent), prefix=".settings-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, SETTINGS_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# v3.x 的 install_hotkeys.sh 在 ~/.claude/commands/ 寫了指標檔，內容是「使用 X plugin
# 的 X skill」。v2 之後 plugin 不再攜帶 skill，指標檔已無用途；只刪內容確實是那個
# 指標檔的（比對特徵字串），使用者自己寫的同名 command 一律不動。
LEGACY_POINTER_NAMES = [
    "redmine",
    "redmine-feature-create",
    "redmine-bug",
    "redmine-bug-create",
    "nineder-google",
    "nineder-google-login",
]


def step4_remove_legacy_pointers() -> None:
    cmds_dir = HOME / ".claude" / "commands"
    if not cmds_dir.is_dir():
        return
    removed = 0
    for name in LEGACY_POINTER_NAMES:
        f = cmds_dir / f"{name}.md"
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "技能清單裡顯示為" in text and "plugin 的 `" in text:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    if removed:
        say(f"nineder-skill：已移除 {removed} 個舊版 plugin 指標檔（~/.claude/commands/），skill 現在直接以裸名提供。")


def step5_sync() -> None:
    sync_sh = SELF_SKILL / "scripts" / "sync.sh"
    if IS_WINDOWS:
        # sync.sh 是 bash 包一段 python3 heredoc，原生 Windows 上還沒有能跑的版本；
        # 這裡先誠實跳過，不假裝同步過。只印一次性的說明，不是每次都念。
        if sync_sh.exists():
            say("nineder-skill：Skill 同步（sync.sh）目前僅支援 macOS／Linux／WSL，原生 Windows 尚未支援；本機的用量排程 hook 不受影響。")
        return
    if sync_sh.exists() and os.access(sync_sh, os.X_OK):
        try:
            subprocess.run(["bash", str(sync_sh), "--auto"], check=False,
                            stdout=None, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def main() -> int:
    step0_version_banner()
    step1_copy_stable_bin()
    step2_seed_nineder_skill()
    step3_settings_hooks()
    step4_remove_legacy_pointers()
    step5_sync()
    return 0


if __name__ == "__main__":
    sys.exit(main())
