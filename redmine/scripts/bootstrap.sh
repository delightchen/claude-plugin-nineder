#!/usr/bin/env bash
# redmine plugin 4.0.7 —— SessionStart bootstrap（分發模型 v2）
# 規格正本：Redmine #26559（v3.3）；分發模型：#26309【分發模型 v2】；同步器：#26915；
# 自動夾帳：#27113（#27090 的手動觸發 skill 衍生出來的裝機步驟）
#
# plugin 在 v2 之後只剩這一支入口，做五件事，順序固定：
#   0. 把 hook 需要的四支腳本複製到 ~/.claude/nineder/bin/（穩定位置）—— 理由見下方 STABLE_BIN
#   1. seed：~/.claude/skills/nineder-skill/ 不存在就從 plugin 的 seed/ 種下去（存在就完全不碰，
#      之後由 Redmine 附檔自我升版——plugin 永遠不覆寫已安裝的版本）
#   2. settings：冪等維護 ~/.claude/settings.json 的 UserPromptSubmit、SessionStart，
#      以及 PreToolUse 的 create_issue／update_issue 兩條自動夾帳 hook
#      （承 #26559 v2.2 並於 v3.1 擴大：桌面版連 plugin 宣告的 hook 都不執行，
#      2026-09-07 實測確認 —— 所以本腳本必須把「呼叫自己」的條目也寫進
#      settings.json，否則 4.0.0 在純桌面版等於完全沒作用）
#   3. 清舊：移除 v3.x 的 ~/.claude/commands/ 指標檔——它們指向 plugin 內已不存在的 skill
#   4. sync：呼叫 ~/.claude/skills/nineder-skill/scripts/sync.sh --auto
#
# 三條不可放寬的界線：
#   * 不碰 ~/.claude.json —— 那是 Claude Code 頻繁寫入的主設定檔，SessionStart 併發寫有風險；
#     MCP 註冊（claude mcp add）交給 /nineder-skill 在對話裡做
#   * 不覆寫已安裝的 skill —— seed 只在目錄不存在時動作
#   * fail-open —— 任何錯誤都 exit 0，絕不阻擋 session 開始
set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SKILLS="${HOME}/.claude/skills"
SELF_SKILL="${SKILLS}/nineder-skill"
STABLE_BIN="${HOME}/.claude/nineder/bin"

# ---- 0. 把 hook 需要的腳本複製到穩定位置 ----
# 為什麼 settings.json 不能直接指向 plugin 目錄（#26915 note-27，2026-09-07 實測）：
# 組織派發的 plugin 放在
#   ~/Library/Application Support/Claude/local-agent-mode-sessions/<session-id>/…/plugin_<id>/
# 這個路徑 *含 session id、每次開對話都會變* ，任何寫進 settings.json 的絕對路徑下次就失效。
# 而 v4.0.3 以前寫死的是 CLI marketplace 路徑，組織派發的機器上那個目錄根本不存在 ——
# 兩條 hook 於是都指向找不到的檔案（fail-open 不會報錯，但等於完全沒作用）。
# 解法：把腳本複製到 ~/.claude/nineder/bin/，settings 條目一律指向這裡 ——
# 兩種派發方式都成立，而且路徑穩定。內容有變才複製，重複執行不動 mtime。
# ai_usage_inline.py／collect.py 兩支是 4.0.7 新增：前者是 PreToolUse hook 本體，
# 後者是它會用 subprocess 呼叫的採集器，兩支必須一起在，缺一支 ai_usage_inline.py
# 會 fail-open 直接放行原始寫入（見該檔 COLLECTOR 判斷）。
copied=0
if [ -f "${PLUGIN_ROOT}/scripts/bootstrap.sh" ] && [ -f "${PLUGIN_ROOT}/scripts/issue_context.sh" ]; then
  if mkdir -p "${STABLE_BIN}" 2>/dev/null; then
    for f in bootstrap.sh issue_context.sh ai_usage_inline.py collect.py; do
      src="${PLUGIN_ROOT}/scripts/${f}"
      dst="${STABLE_BIN}/${f}"
      [ -f "${src}" ] || continue
      if ! cmp -s "${src}" "${dst}" 2>/dev/null; then
        cp "${src}" "${dst}" 2>/dev/null && chmod +x "${dst}" 2>/dev/null && copied=$((copied + 1))
      fi
    done
  fi
fi
[ "${copied}" -gt 0 ] && echo "nineder-skill：已更新 ${copied} 支開機腳本到 ~/.claude/nineder/bin/"

# ---- 1. seed ----
if [ ! -e "${SELF_SKILL}" ]; then
  if [ -d "${PLUGIN_ROOT}/seed/nineder-skill" ]; then
    if mkdir -p "${SKILLS}" 2>/dev/null && cp -R "${PLUGIN_ROOT}/seed/nineder-skill" "${SELF_SKILL}" 2>/dev/null; then
      [ -f "${SELF_SKILL}/scripts/sync.sh" ] && chmod +x "${SELF_SKILL}/scripts/sync.sh" 2>/dev/null
      echo "nineder-skill：已在這台機器種下同步器（種子版）。輸入 /nineder-skill 完成設定。"
    fi
  else
    # 從穩定位置被 hook 呼叫時看不到 plugin 的 seed —— 這是預期，不是錯誤。種子只在第一次
    # 需要，而第一次一定由 /redmine:setup（帶得到 plugin 路徑）觸發。
    echo "nineder-skill：同步器尚未安裝。請在對話中輸入 /redmine:setup 完成首次設定。"
  fi
fi

# ---- 2. settings.json 的 UserPromptSubmit／SessionStart／PreToolUse（承 #26559 v2.2 的
#         install_settings_hook.sh，4.0.7 加入 PreToolUse 自動夾帳，見 #27113）----
if command -v python3 >/dev/null 2>&1; then
python3 - <<'PY' 2>/dev/null || true
import json, os, tempfile

home = os.path.expanduser("~")
path = os.path.join(home, ".claude", "settings.json")
BASE = "$HOME/.claude/nineder/bin/"

# event -> 腳本檔名。都由 settings 層派送：桌面版不執行 plugin 宣告的任何 hook
# （UserPromptSubmit 見 #26559 v2.2；SessionStart 於 2026-09-07 實測確認；PreToolUse
# 同一個限制，2026-09-15 隨 #27113 一併確認），而 settings 層 CLI 與桌面版皆適用且有
# file watcher。SessionStart 指向本腳本自己 —— 這是純桌面版機器唯一跑得到 bootstrap
# 的路徑，所以第一次必須由人手動執行一次本腳本（見 README）。
# 路徑指向 ~/.claude/nineder/bin/（第 0 步複製過去的副本）， *不是* plugin 目錄 ——
# 組織派發的 plugin 路徑含 session id、每次都變，寫進 settings.json 下次就失效。
WANT = {"UserPromptSubmit": "issue_context.sh", "SessionStart": "bootstrap.sh"}

# PreToolUse 跟上面不一樣：需要 matcher 指定攔哪個工具，一支腳本要掛在兩個 matcher
# 上（create_issue 與 update_issue）。ai_usage_inline.py 本身找不到就 fail-open，
# 不影響既有行為，所以晚一版才裝的人也不會被這一步卡住。
WANT_MATCHED = [
    ("PreToolUse", "mcp__nineder-redmine__create_issue", "ai_usage_inline.py"),
    ("PreToolUse", "mcp__nineder-redmine__update_issue", "ai_usage_inline.py"),
]

try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except Exception:
    raise SystemExit          # 讀不到或壞損：完全不碰

hooks = data.setdefault("hooks", {})
changed = False
for event, script in WANT.items():
    # 認得舊版寫進去的條目也要能清掉。4.0.3 以前指向 CLI marketplace 路徑，那條在組織派發
    # 的機器上永遠找不到檔案；只認新 marker 的話舊條目會留在原地變成重複條目（#26915
    # note-27）。所以兩種 marker 都算「我們的」，一律換成新的那一條。
    markers = ("nineder/bin/" + script,
               "marketplaces/nineder/redmine/scripts/" + script)
    cmd = f'SCRIPT="{BASE}{script}"; [ -x "$SCRIPT" ] && exec "$SCRIPT"; exit 0'
    entries = hooks.get(event) or []
    ours = {"hooks": [{"type": "command", "command": cmd}]}
    kept = [e for e in entries
            if not any(m in json.dumps(e) for m in markers)]
    wanted = kept + [ours]
    if wanted != entries:
        hooks[event] = wanted
        changed = True

for event, matcher, script in WANT_MATCHED:
    # 這裡直接呼叫 python3 執行 .py 檔，不走上面那種 shell 轉接殼——PreToolUse 的
    # command 本來就是任意指令，不需要「找不到就 exit 0」那層，腳本自己已經是
    # fail-open（找不到 collect.py 或任何例外都直接放行）。
    cmd = f'python3 {BASE}{script}'
    markers = ("nineder/bin/" + script,)
    entries = hooks.get(event) or []
    ours = {"matcher": matcher, "hooks": [{"type": "command", "command": cmd}]}
    # 用 matcher 也一起認，避免不同 matcher 的條目互相清掉——上面的 markers 只認腳本
    # 名，這裡同一支腳本掛在兩個 matcher 上，必須連 matcher 一起比對才不會誤刪。
    kept = [e for e in entries
            if not (e.get("matcher") == matcher and any(m in json.dumps(e) for m in markers))]
    wanted = kept + [ours]
    if wanted != entries:
        hooks[event] = wanted
        changed = True

if not changed:
    raise SystemExit          # 全部都已就位：不寫、不動 mtime

fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings-", suffix=".json")
try:
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
except Exception:
    try: os.unlink(tmp)
    except OSError: pass
PY
fi

# ---- 3. 清掉 v3.x 的裸名指標檔 ----
# v3.x 的 install_hotkeys.sh 在 ~/.claude/commands/ 寫了指標檔（redmine 四個、google 兩個），
# 內容是「使用 X plugin 的 X skill」。v2 之後 plugin 不再攜帶 skill，這些指標會指向不存在的
# 東西；而 skill 住在 ~/.claude/skills/ 時裸名本來就可用，指標檔已無用途。google plugin 於
# v2 整支廢除，它寫的兩個一併列入 —— 4.0.0 的清單漏了它們，兩個檔留在原地與同名 skill 打
# 對台（2026-09-07 實測）。
# 只刪內容確實是那個指標檔的（比對特徵字串），使用者自己寫的同名 command 一律不動。
CMDS="${HOME}/.claude/commands"
if [ -d "${CMDS}" ]; then
  removed=0
  for n in redmine redmine-feature-create redmine-bug redmine-bug-create nineder-google nineder-google-login; do
    f="${CMDS}/${n}.md"
    [ -f "${f}" ] || continue
    # 判斷依據是 install_hotkeys.sh 產物的兩個特徵句，*不比對 skill 名* —— 4.0.1 拿檔名去
    # 對內文的 skill 名，結果 nineder-google-login.md 沒被清掉：它的內文寫的是「使用 google
    # plugin 的 nineder-google skill」，名稱與檔名不同（2026-09-07 實測）。
    if grep -q "技能清單裡顯示為" "${f}" 2>/dev/null && grep -q "plugin 的 \`" "${f}" 2>/dev/null; then
      rm -f "${f}" 2>/dev/null && removed=$((removed + 1))
    fi
  done
  [ "${removed}" -gt 0 ] && echo "nineder-skill：已移除 ${removed} 個舊版 plugin 指標檔（~/.claude/commands/），skill 現在直接以裸名提供。"
fi

# ---- 4. 同步 ----
SYNC="${SELF_SKILL}/scripts/sync.sh"
[ -x "${SYNC}" ] && bash "${SYNC}" --auto 2>/dev/null

exit 0
