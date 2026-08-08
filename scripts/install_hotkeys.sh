#!/usr/bin/env bash
# SessionStart hook: installs bare-name slash commands (/redmine,
# /redmine-feature-create, /redmine-bug, /redmine-bug-create) that delegate to
# this plugin's namespaced skills.
# Plugin commands are always namespaced (/redmine:redmine) — Claude Code offers
# no way to expose a bare top-level command from a plugin, so these small
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

cat > "${COMMANDS_DIR}/redmine-bug.md" <<'EOF'
---
description: Review 或整理一份 Redmine Bug 描述——分流「回報型/調查型」套用五段結構，指出缺量化、缺失敗鏈、不可複驗之處並給具體改法。只做撰寫與 review，不執行任何 Redmine 寫入
---

使用 `redmine` plugin 的 `redmine-bug` skill（技能清單裡顯示為 `redmine:redmine-bug`）
處理以下任務：$ARGUMENTS

如果上面是空的，代表使用者只打了 `/redmine-bug`，沒有帶任何 Bug 描述——請使用者把要整理
或 review 的問題描述（或 Redmine 議題編號/連結）貼上來。注意：這個指令只做撰寫規範與
review，**不會建立或修改任何 Redmine 議題**；要實際開單請用 `/redmine-bug-create`。
EOF

cat > "${COMMANDS_DIR}/redmine-bug-create.md" <<'EOF'
---
description: 在公司 Redmine 互動式建立一張清楚的 Bug 單——先分流「回報型/調查型」，逐段追問到量化、可複驗，確認後才實際建立議題
---

使用 `redmine` plugin 的 `redmine-bug-create` skill（技能清單裡顯示為
`redmine:redmine-bug-create`）處理以下任務：$ARGUMENTS

如果上面是空的，代表使用者只打了 `/redmine-bug-create`，沒有帶任何問題描述——不要憑空猜
測要開哪張 Bug 單，直接開始互動式訪談流程：先問要開在哪個專案，再問「查出根因了嗎還是只
看到現象」分流，依 skill 裡的步驟逐段問下去。
EOF

exit 0
