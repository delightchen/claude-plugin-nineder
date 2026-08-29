---
description: 在公司 Redmine 互動式建立一張邏輯清楚的 Feature 需求單——依「特性描述+驗收標準+附加資訊」格式逐格提問，把籠統的答案追問到具體，確認後才實際建立議題
---

使用本 plugin 的 `redmine-feature-create` skill（技能清單裡顯示為
`redmine:redmine-feature-create`）處理以下任務：$ARGUMENTS

如果上面是空的，代表使用者只打了這個指令，沒有帶任何具體需求描述——不要憑空猜測要開哪張
需求單，直接開始互動式訪談流程：先問要開在哪個專案，再依 skill 裡的步驟逐格問下去。
