---
name: nineder-google-login
description: 當使用者要把這台機器綁定到某個 nineder.com 的 Google 帳號、要換綁成另一個帳號、要查「這台機器現在是用誰的身份在存取 Google 文件」，或說「重新授權」「Google 連結失效了」「invalid_grant」「我要換帳號」，或輸入 `/nineder-google-login` 時使用。負責走完 MCP 連線設定與 Google OAuth 授權，並且把授權頁開在內建瀏覽器——避開換綁時最容易靜默失敗的地方。退場條件：授權完成後要實際讀寫 Google Docs／Sheets／Slides 請用 `nineder-google`；要撤銷舊帳號在 Google 那邊的授權紀錄，本 skill 做不到，必須由該帳號本人操作。執行過程中對使用者說的話一律用繁體中文。
---

> 版本：v0.1（2026-09-04）｜方法正本：Redmine #26935

# 綁定／換綁公司 Google 帳號 (`/nineder-google-login`)

這支 skill 只做一件事：讓**這台機器**綁定到某一個 nineder.com 的 Google 帳號，或改綁到
另一個。綁好之後的讀寫操作是另一支 skill `nineder-google`（票 [#26934](https://redmine.nineder.com/issues/26934)）。

規格單一事實來源是 Redmine [#26714](https://redmine.nineder.com/issues/26714)。

## 先搞懂身份鏈，不然會問錯問題

| 層級 | 認定方式 |
| --- | --- |
| 機器 | 每台機器一個 Redmine 帳號 |
| MCP 登入 | 同意頁貼上該 Redmine API access key，伺服器當場打 `users/current.json` 驗證，通過才發授權碼。身份即該 Redmine 使用者 id |
| Google 帳號 | Google OAuth 授權，refresh token 以該 Redmine 使用者 id 為鍵、AES-256-GCM 加密存在伺服器 |

三個推論，直接影響怎麼回答使用者：

1. **綁定是「以機器為單位」，不是以人為單位。** 同一個人在三台電腦上可以綁三個不同帳號，
   撤銷其中一台不影響其他台。使用者說「我在公司電腦已經綁好了」時，這台還是要自己綁一次。
2. **同事機器上零憑證。** Google 的 refresh token 只存在伺服器，換機或離職在伺服器端處理，
   不必逐台清理。
3. **要換 Google 帳號不必動 Redmine 身份**，反之亦然——兩層是分開的。使用者說「換帳號」時
   要先問清楚是換哪一層。

## 步驟 1 — 先看現在綁的是誰

呼叫 `google_whoami`，把這台機器**目前**綁的 Redmine 身份與 Google 帳號告訴使用者。

- **工具不存在或呼叫出錯** → 這台機器還沒接上 MCP 服務，走步驟 2。
- **回 `linked` 為 `false`** → MCP 通了但還沒綁 Google，跳到步驟 3。
- **回了一個 Google 帳號** → 先把那個帳號念出來給使用者確認。他要的可能只是「確認一下」，
  那就到此為止；確定要換綁才往下走。

## 步驟 2 — 這台機器還沒接上 MCP 服務

```bash
claude mcp add --scope user --transport http nineder-google https://mcp.nineder.com/google/mcp
claude mcp login nineder-google
```

- **一定要加 `--scope user`**。不加預設是 `local` scope，只註冊在當前專案資料夾，
  症狀是「在某些資料夾能用、其他資料夾不能用」。
- `claude mcp login` 會開瀏覽器到公司的同意頁，要貼上**使用者自己的 Redmine API access
  key**（[Redmine 我的帳戶](https://redmine.nineder.com/my/account) 右側可以取得）。
  這一步決定「這台機器是誰」。
- 沒有瀏覽器可用（例如 SSH）時用 `claude mcp login nineder-google --no-browser`，
  它會印出網址讓使用者在別的裝置完成，再把驗證碼貼回終端機。
- **這一步之後要重新啟動 Claude Code。** 工具 schema 是連線建立當時取得的——登入成功但
  工具還是沒出現**不代表登入失敗**，是這個 session 抓不到新伺服器。不要叫使用者重新登入。
- 先確認 `command -v claude` 找得到 CLI 再執行上面的指令。透過 IDE 擴充或桌面版呼叫時，
  執行環境的 PATH 不一定跟使用者的終端機一樣，`command not found` 不是設定錯誤。

## 步驟 3 — Google 授權（換綁最容易錯的一步）

依序做，不要跳：

1. 呼叫 `google_login` 取得 `authorization_url`。
2. **用 Browser 工具把那個網址開在右欄**（`preview_start` 帶 `url` 參數）。

   ⚠️ **這是刻意的，不是隨手選的**。內建瀏覽器**沒有任何既有的 Google 登入狀態**，會從
   空白登入頁開始，使用者可以乾淨地選要綁的帳號。**用系統瀏覽器的話，Google 同意畫面會
   沿用上次登入的帳號，換綁時直接按允許就會綁回原本那一個，畫面上完全看不出哪裡錯了**
   ——`google_whoami` 回的還是舊帳號，使用者只會覺得「換綁沒生效」卻找不到原因。這是本
   流程唯一的靜默失敗，也是這支 skill 存在的主要理由。

3. 開好之後**停下來等使用者完成**。在使用者說完成之前，**不要讀取、不要截圖那個分頁**
   （`get_page_text`、`read_page`、`screenshot` 一律不要用）——使用者會在裡面輸入
   Google 密碼，那不是該被讀取的內容。
4. 使用者說完成後，**再呼叫一次 `google_whoami` 確認**，把實際綁到的帳號回報出來。
   不要假設成功，使用者可能按了取消或選錯帳號。**換綁時要明確比對「換之前是 A、現在是
   B」**，只說「已完成」等於沒驗證。

如果這個環境沒有 Browser 工具（純 CLI），改成把網址包成可執行的指令給使用者：

```bash
open "<authorization_url>"
```

並補上提醒——系統瀏覽器已登入別的帳號時，要在同意畫面點「使用其他帳戶」，否則就是上面
那個靜默失敗。

使用者若一併指定了要綁的帳號位址，提醒他要選的就是那一個。

## 授權連結與授權效期

| 項目 | 效期 | 過期怎麼辦 |
| --- | --- | --- |
| `google_login` 給的授權連結 | **十分鐘**，且用過即失效 | 再呼叫一次 `google_login` |
| 授權本身（refresh token） | 長期有效，**不會每週失效** | 只有被撤銷或 client 被刪除才需重新授權 |

「不會每週失效」是因為同意畫面設為 Internal。External 測試模式才有七天過期與 100 人上限
的問題，本服務不走那條路。

## 重新授權**不會**撤銷舊帳號的授權紀錄

換綁只會覆蓋伺服器上的 refresh token，**舊帳號在 Google 那邊的「已連結的應用程式」紀錄
還留著**。要完全撤銷得由該帳號本人到 Google 帳號的「已連結的應用程式」頁面移除
`Nineder Claude Workspace`——**這件事你做不到，只能提醒使用者**。交接機器或同事離職時
一定要提醒這一點，否則會留下一筆沒人記得的授權。

## 出錯時怎麼判讀

| 現象 | 意思 | 怎麼處理 |
| --- | --- | --- |
| `google_whoami` 回 `linked` 為 `false` | 還沒授權 | 走步驟 3 |
| 授權完成但 `google_whoami` 還是舊帳號 | **系統瀏覽器沿用了舊登入**，見步驟 3 的警告 | 改用內建瀏覽器重跑一次 |
| `invalid_grant` | 使用者自己撤銷了授權，或管理者刪掉了 OAuth client | 重新走步驟 3 |
| 「授權連結已失效」 | 十分鐘的 state 過期，或連結已用過 | 重新 `google_login` |
| Google 顯示「無存取權限」，本服務沒收到 token | 用了非 nineder.com 網域的帳號 | 換成公司帳號。同意畫面是 Internal，這是預期行為 |
| Google 授權被 Workspace 擋下 | 該帳號不在允許的 OU 或群組內 | 屬於管理端設定，見 [#26781](https://redmine.nineder.com/issues/26781) |
| 登入成功但工具清單裡沒有 | 這個 session 抓不到新伺服器 | 重新啟動 Claude Code，不要重新登入 |
| MCP 連不上但沒有明確錯誤 | 通常是網址寫錯 | 確認是 `https://mcp.nineder.com/google/mcp` |

## 退場條件（什麼時候不要用這支）

| 情況 | 改用什麼 |
| --- | --- |
| 已經綁好了，要實際讀寫 Google 文件 | `nineder-google`（`/nineder-google`） |
| 要撤銷舊帳號在 Google 的授權紀錄 | 做不到，只能請該帳號本人到 Google 帳號設定頁移除 |
| 要限定哪些 OU 或群組可以授權、要封鎖 Claude 內建的 Drive 連接器 | 管理端設定，見 [#26781](https://redmine.nineder.com/issues/26781) |
| 要斷開某位同事 | 伺服器端刪除該使用者的 Google token，屬管理者作業 |
| 要綁的是 Redmine MCP 而不是 Google | `/redmine` |

## 這個 skill 的檢驗標準

一位已經綁著 A 帳號的同事說「幫我改綁成 B」，Claude 應該能自己走完「先報現況是 A → 取
授權網址 → 開在內建瀏覽器 → 停手等他 → 回報現在是 B」，而且**不會**在等待期間去讀那個
分頁，也**不會**只說「已完成」而不比對前後帳號。如果換綁後回報的還是 A 而 Claude 沒察覺，
就是這份文件失效了。
