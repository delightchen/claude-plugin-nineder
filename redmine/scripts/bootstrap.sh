#!/usr/bin/env bash
# redmine plugin 4.0.0 —— SessionStart bootstrap（分發模型 v2）
# 規格正本：Redmine #26559（v3.0）；分發模型：#26309【分發模型 v2】；同步器：#26915
#
# plugin 在 v2 之後只剩這一支入口，做四件事，順序固定：
#   1. seed：~/.claude/skills/nineder-skill/ 不存在就從 plugin 的 seed/ 種下去（存在就完全不碰，
#      之後由 Redmine 附檔自我升版——plugin 永遠不覆寫已安裝的版本）
#   2. settings：冪等維護 ~/.claude/settings.json 的 UserPromptSubmit *與 SessionStart* 兩條
#      （承 #26559 v2.2 並於 v3.1 擴大：桌面版連 plugin 宣告的 SessionStart 都不執行，
#      2026-09-07 實測確認 —— 所以本腳本必須把「呼叫自己」的 SessionStart 條目也寫進
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

# ---- 1. seed ----
if [ ! -e "${SELF_SKILL}" ] && [ -d "${PLUGIN_ROOT}/seed/nineder-skill" ]; then
  if mkdir -p "${SKILLS}" 2>/dev/null && cp -R "${PLUGIN_ROOT}/seed/nineder-skill" "${SELF_SKILL}" 2>/dev/null; then
    [ -f "${SELF_SKILL}/scripts/sync.sh" ] && chmod +x "${SELF_SKILL}/scripts/sync.sh" 2>/dev/null
    echo "nineder-skill：已在這台機器種下同步器（種子版）。輸入 /nineder-skill 完成設定。"
  fi
fi

# ---- 2. settings.json 的 UserPromptSubmit（承 #26559 v2.2 的 install_settings_hook.sh）----
if command -v python3 >/dev/null 2>&1; then
python3 - <<'PY' 2>/dev/null || true
import json, os, tempfile

home = os.path.expanduser("~")
path = os.path.join(home, ".claude", "settings.json")
BASE = "$HOME/.claude/plugins/marketplaces/nineder/redmine/scripts/"

# event -> 腳本檔名。兩條都由 settings 層派送：桌面版不執行 plugin 宣告的任何 hook
# （UserPromptSubmit 見 #26559 v2.2；SessionStart 於 2026-09-07 實測確認），而 settings
# 層 CLI 與桌面版皆適用且有 file watcher。SessionStart 指向本腳本自己 —— 這是純桌面版
# 機器唯一跑得到 bootstrap 的路徑，所以第一次必須由人手動執行一次本腳本（見 README）。
WANT = {"UserPromptSubmit": "issue_context.sh", "SessionStart": "bootstrap.sh"}

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
    marker = "marketplaces/nineder/redmine/scripts/" + script
    cmd = f'SCRIPT="{BASE}{script}"; [ -x "$SCRIPT" ] && exec "$SCRIPT"; exit 0'
    entries = hooks.get(event) or []
    ours = {"hooks": [{"type": "command", "command": cmd}]}
    kept = [e for e in entries if marker not in json.dumps(e)]
    wanted = kept + [ours]
    if wanted != entries:
        hooks[event] = wanted
        changed = True
if not changed:
    raise SystemExit          # 兩條都已就位：不寫、不動 mtime

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
