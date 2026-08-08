---
description: 在公司 Redmine 互動式建立一張清楚的 Bug 單——先分流「回報型/調查型」，逐段追問到量化、可複驗，確認後才實際建立議題
---

使用本 plugin 的 `redmine-bug-create` skill（技能清單裡顯示為
`redmine:redmine-bug-create`）處理以下任務：$ARGUMENTS

如果上面是空的，代表使用者只打了這個指令，沒有帶任何問題描述——不要憑空猜測要開哪張
Bug 單，直接開始互動式訪談流程：先問要開在哪個專案，再問「查出根因了嗎還是只看到現象」
分流，依 skill 裡的步驟逐段問下去。
