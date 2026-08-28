---
name: nineder-google
description: 當使用者要求讀取或修改公司的 Google 文件（Google Docs、試算表 Sheets、簡報 Slides），或輸入 `/nineder_google` 時使用。負責偵測本機是否已連上公司的 Google Workspace MCP、是否已把這台機器綁定到某個 nineder.com 的 Google 帳號，沒有就引導完成，然後執行使用者要的讀寫操作。與 Claude 內建的 Google Drive 連接器不同：內建連接器不能修改既有文件的內文，本服務可以。執行過程中對使用者說的話一律用繁體中文。
---

# 公司 Google 文件讀寫 (`/nineder_google`)

這個 skill 讓 Claude 用**你本人的 nineder.com 帳號**讀取並**修改**公司的 Google
文件。存取範圍等於你在 Google 網頁上看得到的範圍——你沒權限的檔案，這裡一樣拿不到。

規格單一事實來源是 Redmine 議題 "#26714":https://redmine.nineder.com/issues/26714 ；
服務所在的 gateway 由 "#26771":https://redmine.nineder.com/issues/26771 建立。

**為什麼不用 Claude 內建的 Google Drive 連接器**：那條路走 Anthropic 自己的 OAuth，
公司無法控管也無法稽核，而且**它只能搜尋、讀取、建立、改檔名，不能修改既有 Doc 或
簡報的內文**（2026-08-27 實測確認）。要改字、加頁、改儲存格只能用本服務。

## 前置 1 — 確認 MCP 連線

呼叫 `google_whoami`。工具不存在或呼叫出錯，代表這台機器還沒接上服務，引導使用者執行：

```
claude mcp add --scope user --transport http nineder-google https://mcp.nineder.com/google/mcp
claude mcp login nineder-google
```

`claude mcp login` 會開瀏覽器到公司的同意頁，**要貼上你自己的 Redmine API access key**
（在 "Redmine 我的帳戶":https://redmine.nineder.com/my/account 右側可以取得）。這一步決定
「這台機器是誰」——身份鏈是「機器對應一個 Redmine 帳號、Redmine 帳號對應一個 Google 帳號」。

設定完成後**要重新啟動 Claude Code**，工具 schema 是連線建立當時取得的。

## 前置 2 — 確認已綁定 Google 帳號

`google_whoami` 回 `linked` 為 `false` 時，呼叫 `google_login`，把回傳的
`authorization_url` 給使用者，請他在瀏覽器打開、用自己的 nineder.com 帳號按下允許。

授權連結**十分鐘內有效**，過期就再呼叫一次 `google_login`。

因為同意畫面設為 Internal，只有 nineder.com 網域的帳號能通過；用哪個帳號按同意，
這台機器之後就以那個帳號的權限存取檔案。授權一次長期有效，不會每週失效。

完成後再呼叫一次 `google_whoami` 確認，把綁定的 Google 帳號位址回報給使用者——
**不要假設成功**，使用者可能按了取消或選錯帳號。

## 操作流程：先讀再寫，不要盲改

Google 的 batchUpdate 是**座標式**的 API，改東西前一定要先取得座標：

| 目標 | 先做 | 再做 |
| --- | --- | --- |
| 改 Doc 內文 | `docs_read` 取得段落的 `startIndex`／`endIndex` | `docs_batch_update` |
| 改試算表 | `sheets_get` 確認工作表名稱與現有內容 | `sheets_update` |
| 改簡報 | `slides_read` 取得頁面與文字框的 `objectId` | `slides_batch_update` |
| 找檔案 | `drive_search`（Drive 搜尋語法，不是自然語言） | 上面任一支 |

**不知道 fileId 就先 `drive_search`**，不要憑檔名猜——猜錯會去改到別的檔案。

三個實務上最常踩的坑：

1. **Doc 的多處插入要由後往前做**。索引會隨前一個請求位移，由前往後排會全部算錯。
2. **簡報新增頁面要分兩次呼叫**。`createSlide` 當下拿不到版面配置產生的文字框
   `objectId`，得先建、再 `slides_read`、才能寫入。
3. **`sheets_update` 是覆蓋不是追加**。範圍要與資料形狀相符，寫 `A1:B3` 就只動那六格。

## 動手改之前先講清楚要改什麼

寫入類操作（`docs_batch_update`、`sheets_update`、`slides_batch_update`）會直接改動
公司的正式文件，**沒有復原鍵**（Google 的版本記錄可以還原，但那是使用者要自己去翻的）。

所以在呼叫寫入工具之前，先用一兩句話說明「要在哪份檔案、哪個位置、改成什麼」，
讓使用者有機會喊停。使用者已經明確說了要改什麼、改哪裡時不用再問一次——重點是
不要在他只說「幫我看看」的時候就動手改。

改完之後回報實際變更的範圍（回傳值裡的 `updatedRange`、`appliedRequests` 等），
不要只說「已完成」。

## 刪除檔案預設不開放

`drive_trash` 由伺服器端的 `ENABLE_GOOGLE_DESTRUCTIVE` 旗標控制，**預設關閉**，
所以工具清單裡通常看不到它。使用者要求刪檔案而工具不存在時，說明這是刻意的設計，
請他自己到 Google Drive 操作，或聯絡管理者開啟該旗標。

## 出錯時怎麼判讀

| 現象 | 意思 | 怎麼處理 |
| --- | --- | --- |
| 工具回「這台機器尚未連結 Google 帳號」 | 前置 2 沒做 | 呼叫 `google_login` |
| 「無法用 refresh token 取得 access token」含 `invalid_grant` | 使用者撤銷了授權，或管理者刪掉了 OAuth client | 重新 `google_login` |
| Google 回 403 或 404 | 該帳號對那個檔案沒有權限，或 fileId 錯 | 用 `drive_search` 確認檔案與權限，不要重試同一個 id |
| 「授權連結已失效」 | 十分鐘的 state 過期，或連結已用過 | 重新 `google_login` |
| MCP 連不上但沒有明確錯誤 | 通常是設定網址錯誤 | 確認網址是 `https://mcp.nineder.com/google/mcp` |

## 這個 skill 的檢驗標準

使用者說「幫我把這份週報試算表的八月數字更新成這幾筆」時，Claude 應該能自己走完
「搜尋檔案 → 讀現況 → 說明要改什麼 → 寫入 → 回報實際變更範圍」，中間不需要使用者
教它任何一步。如果卡在某一步不知道下一步該做什麼，代表這份文件還沒寫到位。
