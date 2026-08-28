---
description: 綁定或重新綁定這台機器要用的 nineder.com Google 帳號——授權頁會開在右欄的內建瀏覽器（無既有登入狀態，可乾淨選帳號）
---

使用 `google` plugin 的 `nineder-google` skill（技能清單裡顯示為
`google:nineder-google`），只執行「綁定 Google 帳號」這一段，依序做：

1. 先呼叫 `google_whoami`，把這台機器**目前**綁的 Redmine 身份與 Google 帳號告訴使用者。
2. 呼叫 `google_login` 取得 `authorization_url`。
3. **用 Browser 工具把那個網址開在右欄**（`preview_start` 帶 `url` 參數）。這是刻意的：
   內建瀏覽器**沒有任何既有的 Google 登入狀態**，所以會從空白的登入頁開始，使用者可以
   乾淨地選要綁的帳號。用系統瀏覽器的話，Google 同意畫面會沿用上次登入的帳號，換綁時
   直接按允許就會綁回原本那個，看起來像沒換成功——這是最常踩的坑。
4. 開好之後**停下來等使用者完成**。在使用者說完成之前，**不要讀取、不要截圖那個分頁**
   （`get_page_text`、`read_page`、`screenshot` 一律不要用）——使用者會在裡面輸入
   Google 密碼，那不是該被讀取的內容。
5. 使用者說完成後，**再呼叫一次 `google_whoami` 確認**，把實際綁到的帳號回報出來。
   不要假設成功，使用者可能按了取消或選錯帳號。

如果這個環境沒有 Browser 工具（純 CLI），改成把網址包成可執行的指令給使用者：
`open "<authorization_url>"`，並補上第 3 點的提醒——系統瀏覽器已登入別的帳號時，
要在同意畫面點「使用其他帳戶」。

$ARGUMENTS

如果上面帶了帳號位址，提醒使用者要選的就是那一個。

補充：重新授權只會覆蓋伺服器上的 refresh token，**不會撤銷舊帳號在 Google 那邊的授權紀錄**。
要完全撤銷得由該帳號本人到 Google 帳號的「已連結的應用程式」頁面移除
`Nineder Claude Workspace`。交接機器或離職時要提醒這一點。
