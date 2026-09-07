#!/usr/bin/env bash
# redmine plugin 4.0.0 —— SessionStart bootstrap（分發模型 v2）
# 規格正本：Redmine #26559（v3.0）；分發模型：#26309【分發模型 v2】；同步器：#26915
#
# plugin 在 v2 之後只剩這一支入口，做四件事，順序固定：
#   1. seed：~/.claude/skills/nineder-skill/ 不存在就從 plugin 的 seed/ 種下去（存在就完全不碰，
#      之後由 Redmine 附檔自我升版——plugin 永遠不覆寫已安裝的版本）
#   2. settings：冪等維護 ~/.claude/settings.json 的 UserPromptSubmit 條目（承 #26559 v2.2：
#      桌面版不執行 plugin 宣告的 UserPromptSubmit，settings 層才 CLI/Desktop 通用）
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
marker = "marketplaces/nineder/redmine/scripts/issue_context.sh"
cmd = ('SCRIPT="$HOME/.claude/plugins/marketplaces/nineder/redmine/scripts/issue_context.sh"; '
       '[ -x "$SCRIPT" ] && exec "$SCRIPT"; exit 0')

try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except Exception:
    raise SystemExit          # 讀不到或壞損：完全不碰

hooks = data.setdefault("hooks", {})
entries = hooks.get("UserPromptSubmit") or []
ours = {"hooks": [{"type": "command", "command": cmd}]}
kept = [e for e in entries if marker not in json.dumps(e)]
wanted = kept + [ours]
if wanted == entries:
    raise SystemExit          # 已就位：不寫、不動 mtime
hooks["UserPromptSubmit"] = wanted

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
# v3.x 的 install_hotkeys.sh 在 ~/.claude/commands/ 寫了四個指標檔，內容是「使用 redmine
# plugin 的 <名> skill」。v2 之後 plugin 不再攜帶 skill，這些指標會指向不存在的東西；而 skill
# 住在 ~/.claude/skills/ 時裸名本來就可用，指標檔已無用途。
# 只刪內容確實是那個指標檔的（比對特徵字串），使用者自己寫的同名 command 一律不動。
CMDS="${HOME}/.claude/commands"
if [ -d "${CMDS}" ]; then
  removed=0
  for n in redmine redmine-feature-create redmine-bug redmine-bug-create; do
    f="${CMDS}/${n}.md"
    [ -f "${f}" ] || continue
    if grep -q "plugin 的 \`${n}\` skill" "${f}" 2>/dev/null && grep -q "技能清單裡顯示為" "${f}" 2>/dev/null; then
      rm -f "${f}" 2>/dev/null && removed=$((removed + 1))
    fi
  done
  [ "${removed}" -gt 0 ] && echo "nineder-skill：已移除 ${removed} 個舊版 plugin 指標檔（~/.claude/commands/），skill 現在直接以裸名提供。"
fi

# ---- 4. 同步 ----
SYNC="${SELF_SKILL}/scripts/sync.sh"
[ -x "${SYNC}" ] && bash "${SYNC}" --auto 2>/dev/null

exit 0
