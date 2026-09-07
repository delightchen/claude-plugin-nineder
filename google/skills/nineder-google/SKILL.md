---
name: nineder-google
description: 當使用者要求讀取或修改公司的 Google 文件（Google Docs、試算表 Sheets、簡報 Slides），例如「幫我改這份文件的內文」「更新週報試算表的數字」「在這份簡報加一頁」「幫我找公司雲端硬碟上的某份檔案」，或輸入 `/nineder-google` 時使用。負責偵測本機是否已連上公司的 Google Workspace MCP、是否已把這台機器綁定到某個 nineder.com 的 Google 帳號，沒有就引導完成，然後執行使用者要的讀寫操作。與 Claude 內建的 Google Drive 連接器不同：內建連接器不能修改既有文件的內文，本服務可以。退場條件：只是要綁定或換綁 Google 帳號請用 `nineder-google-login`；要動的是私人 Google 帳號、非 nineder.com 網域的檔案、或需要公式與自動型別的試算表寫入，本 skill 都做不到。執行過程中對使用者說的話一律用繁體中文。
---

> 版本：v0.1（2026-09-04）｜方法正本：Redmine #26934

# 公司 Google 文件讀寫 (`/nineder-google`)

這個 skill 讓 Claude 用**你本人的 nineder.com 帳號**讀取並**修改**公司的 Google
文件。存取範圍等於你在 Google 網頁上看得到的範圍——你沒權限的檔案，這裡一樣拿不到。

規格單一事實來源是 Redmine [#26714](https://redmine.nineder.com/issues/26714)；服務所在的
gateway 由 [#26771](https://redmine.nineder.com/issues/26771) 建立。

**為什麼不用 Claude 內建的 Google Drive 連接器**：那條路走 Anthropic 自己的 OAuth，
公司無法控管也無法稽核，而且**它只能搜尋、讀取、建立、改檔名，不能修改既有 Doc 或
簡報的內文**。2026-08-27 三次實測確認：讀取既有簡報成功、建立新簡報成功、修改既有內文
「工具根本不存在」，而且三次操作期間公司 GCP 專案的 API 請求數**都是零**。要改字、加頁、
改儲存格只能用本服務。

## 使用資格是兩道閘門，不是一道

|  | 為什麼 | 沒有的話 |
| --- | --- | --- |
| 有 Redmine 帳號並能取得 API access key | MCP 登入的同意頁會當場打 Redmine 的 `users/current.json` 驗證 | 發不出 MCP token，連 `google_login` 都呼叫不到 |
| 有 nineder.com 網域的 Google 帳號 | 同意畫面設為 Internal | Google 直接在授權頁擋下，本服務拿不到任何 token |

兩道都過了才有更細的分眾控管問題——那部分在 Workspace 管理主控台的應用程式存取控制，
不在本服務內，追蹤於 [#26781](https://redmine.nineder.com/issues/26781)。

## 前置 1 — 確認 MCP 連線

呼叫 `google_whoami`。工具不存在或呼叫出錯，代表這台機器還沒接上服務，引導使用者執行：

```bash
claude mcp add --scope user --transport http nineder-google https://mcp.nineder.com/google/mcp
claude mcp login nineder-google
```

`claude mcp login` 會開瀏覽器到公司的同意頁，**要貼上你自己的 Redmine API access key**
（在 [Redmine 我的帳戶](https://redmine.nineder.com/my/account) 右側可以取得）。這一步決定
「這台機器是誰」——身份鏈是「機器對應一個 Redmine 帳號、Redmine 帳號對應一個 Google 帳號」。

**一定要加 `--scope user`**。不加的話預設是 `local` scope，只會註冊在「你現在剛好待著的
那一個專案資料夾」，症狀是「在某些資料夾能用、其他資料夾不能用」。

設定完成後**要重新啟動 Claude Code**，工具 schema 是連線建立當時取得的——登入成功但工具
還是沒出現，不代表登入失敗，是這個 session 抓不到新伺服器。

## 前置 2 — 確認已綁定 Google 帳號

`google_whoami` 回 `linked` 為 `false` 時，呼叫 `google_login`，把回傳的
`authorization_url` 給使用者，請他用自己的 nineder.com 帳號按下允許，完成後**再呼叫一次
`google_whoami` 確認實際綁到哪個帳號**——不要假設成功，使用者可能按了取消或選錯帳號。

授權連結**十分鐘內有效**，過期就再呼叫一次 `google_login`。授權一次長期有效，不會每週失效。

⚠️ **換綁（已經綁了 A 帳號、要改綁 B 帳號）不要用系統瀏覽器開授權頁**：系統瀏覽器已登入
A 時，Google 同意畫面會直接沿用 A，按下允許就綁回原本那個，畫面上完全看不出哪裡錯了。
完整的綁定與換綁流程是另一支 skill `nineder-google-login`（指令 `/nineder-google-login`，票 [#26935](https://redmine.nineder.com/issues/26935)）；
只是要換帳號就直接用它，不要在這裡自己想辦法。

## 操作流程：先讀再寫，不要盲改

Google 的 batchUpdate 是**座標式**的 API，改東西前一定要先取得座標：

| 目標 | 先做 | 再做 |
| --- | --- | --- |
| 改 Doc 內文 | `docs_read` 取得段落的 `startIndex`／`endIndex` | `docs_batch_update` |
| 改試算表 | `sheets_get` 確認工作表名稱與現有內容 | `sheets_update` |
| 改簡報 | `slides_read` 取得頁面與文字框的 `objectId` | `slides_batch_update` |
| 找檔案 | `drive_search`（Drive 搜尋語法，不是自然語言） | 上面任一支 |

**不知道 fileId 就先 `drive_search`**，不要憑檔名猜——猜錯會去改到別的檔案。

## 四個實務上最常踩的坑（前三個都是靜默失敗）

1. **同一個批次裡的索引會互相位移，多處修改要由後往前排。** 2026-08-27 實測重現：在同一
   批次先送 `replaceAllText` 再送 `insertText`，`insertText` 用的是**批次執行前**讀到的
   索引，結果文字插進錯誤位置、把一行字從中間切開。Google 回 200，沒有任何錯誤。
   對策：索引大的先做，或改完一次就重讀一次再算下一個。
2. **`sheets_update` 是覆蓋不是追加。** 範圍要與資料形狀相符，寫 `A1:B3` 就只動那六格；
   範圍給大了，多出來的格子會被清空。
3. **簡報新增頁面必須分兩次呼叫。** `createSlide` 當下拿不到版面配置產生的文字框
   `objectId`，得先建、再 `slides_read`、才能寫入。一次搞定的寫法會靜默寫不進去。
4. **試算表寫入是 RAW 模式，寫進去的就是字面值。** 2026-08-28 實測：寫入 `0912345678`
   讀回仍是 `0912345678`，**開頭的零沒有被吃掉**。這是刻意的選擇——若用
   `USER_ENTERED`，電話號碼會變成數字、`1-2` 會變成日期。反面代價是**本服務不能寫公式**
   （寫 `=SUM(A1:A9)` 進去就是那串字面文字，不會計算），需要公式請使用者自己在 Google
   試算表裡填。

## 動手改之前先講清楚要改什麼

寫入類操作（`docs_batch_update`、`sheets_update`、`slides_batch_update`）會直接改動
公司的正式文件，**沒有復原鍵**（Google 的版本記錄可以還原，但那是使用者要自己去翻的）。

所以在呼叫寫入工具之前，先用一兩句話說明「要在哪份檔案、哪個位置、改成什麼」，
讓使用者有機會喊停。使用者已經明確說了要改什麼、改哪裡時不用再問一次——重點是
不要在他只說「幫我看看」的時候就動手改。

改完之後回報實際變更的範圍（回傳值裡的 `updatedRange`、`appliedRequests`、
`occurrencesChanged` 等），不要只說「已完成」。

## 三級工具開關：看不到某支工具通常是刻意的

伺服器端分三級註冊，共 12 支，預設出現 11 支：

| 級別 | 工具 | 開關 |
| --- | --- | --- |
| 唯讀 | `google_login`、`google_whoami`、`google_logout`、`drive_search`、`docs_read`、`sheets_get`、`slides_read` | 永遠註冊 |
| 寫入 | `docs_batch_update`、`sheets_update`、`slides_batch_update`、`drive_create` | `ENABLE_WRITE_TOOLS` |
| 破壞性 | `drive_trash` | `ENABLE_GOOGLE_DESTRUCTIVE`，**預設關閉** |

使用者要求刪檔案而 `drive_trash` 不存在時，說明這是刻意的設計（刪掉他人檔案與改錯一格
試算表不是同一個風險等級，所以用獨立旗標），請他自己到 Google Drive 操作，或聯絡管理者
開啟該旗標。**不要試圖用其他工具繞過去達成刪除。**

## 出錯時怎麼判讀

⚠️ **已知缺陷：工具拋出的 Google 錯誤原因目前不會透到使用者端**（[#26714](https://redmine.nineder.com/issues/26714)
2026-08-28 記錄）。實測把工作表名稱誤寫成「工作表1」（新建的試算表實際叫 `Sheet1`），
Google 回 400 並附明確原因，但客戶端只顯示 `Error executing tool sheets_update`。
**所以看到這種沒有原因的錯誤訊息時，第一個要懷疑的是名稱或 id 猜錯了，不是服務壞了**——
回頭用 `sheets_get`／`drive_search` 把真實名稱查出來，不要重試同一組參數。

| 現象 | 意思 | 怎麼處理 |
| --- | --- | --- |
| 工具回「這台機器尚未連結 Google 帳號」 | 前置 2 沒做 | 呼叫 `google_login`，或改用 `nineder-google-login` |
| 「無法用 refresh token 取得 access token」含 `invalid_grant` | 使用者撤銷了授權，或管理者刪掉了 OAuth client | 重新 `google_login` |
| Google 回 403 或 404 | 該帳號對那個檔案沒有權限，或 fileId 錯 | 用 `drive_search` 確認檔案與權限，不要重試同一個 id |
| 「授權連結已失效」 | 十分鐘的 state 過期，或連結已用過 | 重新 `google_login` |
| 只有 `Error executing tool ...`，沒有原因 | 見上方已知缺陷，通常是工作表名稱或 id 錯 | 先查真實名稱，不要重試 |
| MCP 連不上但沒有明確錯誤 | 通常是設定網址錯誤 | 確認網址是 `https://mcp.nineder.com/google/mcp` |

## 退場條件（什麼時候不要用這支）

| 情況 | 改用什麼 |
| --- | --- |
| 只是要綁定或換綁 Google 帳號 | `nineder-google-login`（`/nineder-google-login`） |
| 要動私人 Google 帳號或非 nineder.com 網域的檔案 | 做不到，同意畫面是 Internal。請使用者自己在 Google 網頁操作 |
| 試算表需要公式、需要 Google 自動判斷型別 | 做不到（RAW 模式），請使用者自己填 |
| 要刪除檔案 | `drive_trash` 預設關閉，請使用者自己到 Drive 操作 |
| 要改的是 Redmine 議題 | `/redmine` |

## 這個 skill 的檢驗標準

使用者說「幫我把這份週報試算表的八月數字更新成這幾筆」時，Claude 應該能自己走完
「搜尋檔案 → 讀現況 → 說明要改什麼 → 寫入 → 回報實際變更範圍」，中間不需要使用者
教它任何一步；而且在拿到一則沒有原因的 `Error executing tool` 時，會自己去查真實的
工作表名稱而不是重試。如果卡在某一步不知道下一步該做什麼，代表這份文件還沒寫到位。
