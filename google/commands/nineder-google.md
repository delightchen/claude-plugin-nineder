---
description: 用你本人的 nineder.com 帳號讀取並修改公司的 Google Docs、Sheets、Slides——含修改既有文件內文（Claude 內建連接器做不到的那件事）
---

使用本 plugin 的 `nineder-google` skill（技能清單裡顯示為
`google:nineder-google`）處理以下任務：$ARGUMENTS

如果上面是空的，代表使用者只打了這個指令，沒有說要做什麼——不要憑空猜測要動哪份檔案。
先依 skill 的前置步驟確認連線與 Google 帳號綁定狀態，回報這台機器目前綁的是哪個帳號，
然後問使用者要對哪份文件做什麼。
