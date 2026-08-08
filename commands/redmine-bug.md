---
description: Review 或整理一份 Redmine Bug 描述——分流「回報型/調查型」套用五段結構，指出缺量化、缺失敗鏈、不可複驗之處並給具體改法。只做撰寫與 review，不執行任何 Redmine 寫入
---

使用本 plugin 的 `redmine-bug` skill（技能清單裡顯示為 `redmine:redmine-bug`）處理以下
任務：$ARGUMENTS

如果上面是空的，代表使用者只打了這個指令，沒有帶任何 Bug 描述——請使用者把要整理或
review 的問題描述（或 Redmine 議題編號/連結）貼上來。注意：這個指令只做撰寫規範與
review，**不會建立或修改任何 Redmine 議題**；要實際開單請用 `/redmine-bug-create`。
