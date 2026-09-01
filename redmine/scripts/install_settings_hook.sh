#!/usr/bin/env bash
# SessionStart hook: idempotently ensures the user-level ~/.claude/settings.json
# declares the UserPromptSubmit hook that runs this plugin's issue_context.sh.
#
# Why settings.json instead of the plugin's own hooks.json: the Desktop app does
# not execute plugin-declared UserPromptSubmit hooks (known CLI/Desktop parity
# gap — github.com/anthropics/claude-code issue 45514), while hooks declared in
# ~/.claude/settings.json are documented to apply to both CLI and Desktop and
# are picked up by a file watcher. To avoid double injection in environments
# that honor both, the plugin's hooks.json intentionally does NOT declare
# UserPromptSubmit — this settings entry is the single execution path.
# Spec: https://redmine.nineder.com/issues/26559 (v2.2)
#
# The managed entry uses $HOME at runtime (portable across members) and guards
# on the script's existence, so uninstalling the plugin leaves a hook that
# silently no-ops instead of erroring on every prompt.
# Deterministic + idempotent: identifies its own entry by the script path,
# replaces stale variants, writes atomically, and skips the write entirely when
# nothing changes. Never touches other hooks. Fails open: any problem
# (no python3, unreadable/corrupt settings.json) leaves the file alone and
# exits 0, silently.
set -uo pipefail

command -v python3 >/dev/null 2>&1 || exit 0

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
    raise SystemExit  # unreadable or corrupt: leave it alone

hooks = data.setdefault("hooks", {})
entries = hooks.get("UserPromptSubmit") or []
ours = {"hooks": [{"type": "command", "command": cmd}]}
kept = [e for e in entries if marker not in json.dumps(e)]
wanted = kept + [ours]
if wanted == entries:
    raise SystemExit  # already exactly in place: no write, no mtime churn
hooks["UserPromptSubmit"] = wanted

fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings-", suffix=".json")
try:
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
PY
exit 0
