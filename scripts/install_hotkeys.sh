#!/usr/bin/env bash
# SessionStart hook: installs bare-name slash commands (/redmine,
# /redmine-feature-create) that delegate to this plugin's namespaced skills.
# Plugin commands are always namespaced (/redmine:redmine) — Claude Code offers
# no way to expose a bare top-level command from a plugin, so these two small
# pointer files in ~/.claude/commands/ are the only per-machine artifacts.
# Deterministic + idempotent: runs on every session start, rewrites both files
# unconditionally (they are tiny), never touches skill content. Stays silent on
# success so nothing is injected into the session context.
set -uo pipefail

COMMANDS_DIR="${HOME}/.claude/commands"
mkdir -p "${COMMANDS_DIR}"

cat > "${COMMANDS_DIR}/redmine.md" <<'EOF'
---
description: 存取公司 Redmine(redmine.nineder.com)——查詢、建立、更新議題、記錄工時,並自動處理這台機器的一次性授權設定
---

使用 `redmine` plugin 的 `redmine` skill(技能清單裡顯示為 `redmine:redmine`)處理以下任
務:$ARGUMENTS

如果上面是空的,代表使用者只打了 `/redmine`,沒有帶任何具體任務——照該 skill 裡「步驟 3」
最後一段的說明處理:不要憑空猜測要做什麼,只要回報連線狀態,如果正常就順便列出可用的工具。
EOF

cat > "${COMMANDS_DIR}/redmine-feature-create.md" <<'EOF'
---
description: 在公司 Redmine 互動式建立一張邏輯清楚的 Feature 需求單——依「特性描述+驗收標準+附加資訊」格式逐格提問，把籠統的答案追問到具體，確認後才實際建立議題
---

使用 `redmine` plugin 的 `redmine-feature-create` skill（技能清單裡顯示為
`redmine:redmine-feature-create`）處理以下任務：$ARGUMENTS

如果上面是空的，代表使用者只打了 `/redmine-feature-create`，沒有帶任何具體需求描述——不要
憑空猜測要開哪張需求單，直接開始互動式訪談流程：先問要開在哪個專案，再依 skill 裡的步驟逐
格問下去。
EOF

exit 0
