---
name: redmine
description: 當使用者輸入 `/redmine`,或要求查詢、建立、更新公司 Redmine 議題追蹤系統(redmine.nineder.com)裡的任何內容時使用這個 skill——包括列出議題、查詢狀態、建立工單、更新工單、記錄工時、搜尋、列出專案。當任何 Redmine MCP 工具呼叫失敗並出現驗證/連線錯誤時(invalid_token、401、tool not found),也要主動使用這個 skill——它會自動處理一次性的機器設定(`claude mcp add`/`claude mcp login`),所以不要在還沒試過這個 skill 的設定流程之前,就直接把錯誤回報給使用者。執行過程中對使用者說的話一律用繁體中文,不要用英文。
---

# Redmine (`/redmine`)

**無論使用者用什麼語言輸入,執行這個 skill 期間,你對使用者說的每一句話都必須是繁體中
文,不可以用英文。** 下面的指示是寫給你(Claude)看的操作步驟,不代表你回覆使用者時也要
照抄英文技術詞彙以外的部分——bash 指令、工具名稱、參數名稱維持原樣即可,但所有說明、
提示、確認訊息一律用繁體中文組織成句子講給使用者聽。

讓 `/redmine <任務>` 變成一個「直接就能用」的單一指令,不管這台電腦有沒有跟組織的
Redmine MCP 伺服器溝通過,也不管 Claude Code 現在是在哪一個專案資料夾底下執行。在全新
的機器上,它會透明地引導使用者完成一次性設定;在已經設定好的機器上,它會直接執行
`<任務>`。

## 這個 skill 怎麼發佈與更新(給維護者看的背景)

本 skill 與 `redmine-feature`(Feature 需求撰寫規範)、`redmine-feature-create`(互動建立
Feature 需求單)一起打包成組織等級的 Claude Plugin(plugin 名稱 `redmine`)發佈——組織成
員安裝一次 plugin,三個 skill 與對應指令就全部到位,版本一致性由 plugin 機制保證,不再需
要任何「執行時在本機寫檔同步」的動作。發佈與規格追蹤在 Redmine
議題 "#26309":https://redmine.nineder.com/issues/26309 ;本 skill 的行為規格單一事實來源是
"#26311":https://redmine.nineder.com/issues/26311 (基本寫入準則)——**之後要修改本 skill 的
任何行為,先修訂 #26311 的 Description(遵守下面的防互蓋流程),再同步改這份檔案,並發佈
新版 plugin(記得把 plugin.json 的 version 往上推,否則自動更新會跳過這一版)。**

## 為什麼設定是「以機器為單位」,而不是「以帳號為單位」

Redmine 的存取是透過一個遠端 MCP 伺服器
(`https://mcp.redmine.nineder.com/mcp`),每個人都用自己的 Redmine API key 個別驗證身份。
Claude Code 對遠端 MCP 伺服器的 OAuth 登入(`claude mcp login`)會把產生的憑證
**只存在這台機器上**——不會透過使用者的 Claude 帳號同步,也不會分享到他的其他電腦上。
這是刻意設計的:一個人在三台不同電腦上使用 Claude,完全可以(而且經常會)在每台電腦用
不同的 Redmine 身份,撤銷其中一台機器的存取權也完全不會影響到其他台。這也代表:一台從
沒跑過 `claude mcp login` 的電腦,不管這個人在其他多少台機器上已經設定好了,這台機器都
還是沒有存取權——第一件要檢查的事,永遠是針對*這台機器*,而不是針對這個人。

## 步驟 1 — 檢查這台機器現在能不能連上 Redmine

如果目前的工具清單裡有 `redmine` MCP 連接器,就呼叫它的 `get_current_user` 工具。這個呼叫
成本很低,而且能告訴你所有需要知道的資訊:

- **成功** → 這台機器已經設定好了,直接跳到步驟 3。
- **工具清單裡完全找不到這個工具** → 這台機器從來沒有設定過 `redmine` MCP 伺服器。前往
  步驟 2 的「尚未設定」。
- **工具存在,但呼叫出錯**(`invalid_token`、401、unauthorized)→ 連接器已經設定好了,
  只是儲存的憑證過期或被撤銷了。前往步驟 2 的「過期或被撤銷」。

## 步驟 2 — 引導使用者完成設定

在執行任何 `claude mcp` 指令之前,先確認這台機器上真的裝了 `claude` 這個 CLI 指令。雖然你
現在就是透過 Claude Code 在執行這個 skill,但如果使用者是透過 IDE 擴充套件(VS Code、
JetBrains)或桌面版/網頁版介面呼叫的,那個執行環境的 PATH 不一定跟使用者自己開的終端機
一樣——`claude mcp add`/`claude mcp login` 有可能因為「command not found」直接失敗,那不
是設定錯誤,是這台機器根本還沒裝 CLI。

用 Bash 檢查一次(這只是查詢,不會動到任何東西,可以放心直接做,不用先問過使用者):

```bash
command -v claude
```

- **找得到** → 直接往下走,執行下面「尚未設定」或「過期或被撤銷」對應的指令。
- **找不到(command not found)** → 不要嘗試自己動手安裝——安裝方式要看使用者的作業系統
  與環境習慣(有沒有 Homebrew、有沒有 Node.js),這個選擇應該留給使用者自己做。跟他說清
  楚現況,並列出官方支援的幾種安裝方式讓他自己選一種:

  ```bash
  # 官方安裝腳本(macOS/Linux 都適用)
  curl -fsSL https://code.claude.com/install.sh | sh

  # 或用 Homebrew(macOS/Linux)
  brew install claude-code

  # 或用 npm(跨平台,需要先裝 Node.js)
  npm install -g @anthropic-ai/claude-code
  ```

  提醒他裝完之後要開一個**新的終端機視窗**(讓新的 PATH 生效),再回來繼續。在確認
  `command -v claude` 找得到之前,不要往下執行任何 `claude mcp` 指令,也不要假裝已經裝好。

### 尚未設定

自己透過 Bash 執行下面這行指令——它只是註冊伺服器位址,不會驗證任何人的身份,所以可以
放心直接執行,不用先問過使用者。**一定要加上 `--scope user`**——如果沒加,
`claude mcp add` 預設會用 `local` scope,那樣只會把伺服器註冊在「你現在剛好待著的那一個
專案資料夾」裡,不會套用到整台機器。這個預設值正是造成「`/redmine` 在某些專案資料夾能用、
其他資料夾不能用」的真正原因——從來就不是同步/傳播的問題,而是 scope 設錯了。

```bash
claude mcp add --transport http --scope user redmine https://mcp.redmine.nineder.com/mcp
```

如果這台機器上 `redmine` 已經註冊過,但只是用 `local` scope(用 `claude mcp list` 檢查——
如果只有在特定幾個專案資料夾才能用,原因就是這個),先把那些殘留的 local 註冊清掉,免得
留著造成混淆,再用 `user` scope 重新加回去:

```bash
claude mcp remove redmine --scope local
claude mcp add --transport http --scope user redmine https://mcp.redmine.nineder.com/mcp
```

接著要老實跟使用者說,還差最後一步需要他親自動手,因為那是一個互動式的瀏覽器登入,你沒
辦法代替他完成:

```bash
claude mcp login redmine
```

先跟他說清楚接下來會發生什麼事,才不會嚇到他:這個指令會開啟瀏覽器,連到 Redmine MCP
伺服器自己的登入頁面,使用者要在那裡貼上自己**個人的 Redmine API access key**(在 Redmine
→ 我的帳戶 → API access key,頁面右上角可以找到)。完成後,產生的存取權杖只會存在這台
機器上。要明確跟他說這是「以機器為單位」的——如果他也在其他電腦上用 Claude,每一台都需
要各自單獨執行一次 `claude mcp login redmine`,而且每一台都可以用不同的 Redmine 身份,
如果他想要的話。

如果這裡沒有瀏覽器可用(例如透過 SSH 連線的情況),改給他這個指令:

```bash
claude mcp login redmine --no-browser
```

這個指令會印出一個網址,而不是直接開啟瀏覽器。使用者可以在任何有瀏覽器的裝置上打開這個
網址完成登入,然後把它給的驗證碼貼回這個終端機。

在使用者說他完成之前,**先等待**,不要往下走——工具在這之前是真的還不能用,不要提早進
行步驟 3,也不要假裝它已經可以用。

當他說做完了之後,用同樣的方式再檢查一次(試著呼叫 `get_current_user`)。如果登入明明成
功了,但工具清單裡還是找不到這個工具,那不代表登入失敗——這代表*目前這個正在執行的對
話*還沒有抓到新加入的伺服器(工具清單在一次對話的生命週期內是固定的)。要跟使用者說登入
其實是成功的,只是他需要開一個**全新的對話**,工具才會真的出現,而不是要他重新登入一
次,或是覺得哪裡出了問題。

### 過期或被撤銷

跟上面步驟一樣,但跳過 `claude mcp add`——伺服器本來就已經註冊過了,只需要重新整理憑證:

```bash
claude mcp login redmine
```

## 步驟 3 — 執行實際任務

一旦確認 `redmine` 工具能正常運作(不管是從步驟 1 就確認,還是使用者剛完成登入之後),就
根據使用者的需求選擇合適的工具:

- `get_current_user` — 確認身份 / 連線狀態
- `list_issues`、`list_my_issues`、`get_issue`、`search`、`list_projects` —
  唯讀查詢類
- `create_issue`、`update_issue` — 支援 Redmine 自己的議題表單所有欄位:標題、描述、
  追蹤標籤(tracker)、狀態、優先權、指派對象、父議題(子議題)、分類、版本、日期、預估
  工時、完成度、隱私設定、自訂欄位,以及(僅限建立時)關注者。不同專案可能因為工作流程
  不同而要求不同的必填欄位——如果呼叫失敗,錯誤訊息會指出缺少哪個欄位,補上之後重試,
  不要就此放棄。
- `add_time_entry` — 針對特定議題或專案直接記錄工時。

以上三個工具會改變 Redmine 裡的資料。只有在使用者的需求明確要求做出變更時(建立東西、
更新東西、記錄工時),才呼叫它們——不要建立或修改任何使用者沒有要求的東西,也不要因為
「感覺是自然的下一步」就多做一個使用者沒有要求的寫入動作。

### 上傳附件(截圖/檔案)時,改用本機腳本拿 token,不要用 `content_base64`

`upload_attachment` 這個 MCP 工具雖然接受 `content_base64` 參數,但只適合幾 KB 內的小檔
案。這個 MCP server 是部署在公司 VM 上的 remote MCP(`https://mcp.redmine.nineder.com`),
跟你現在執行的 Claude Code 不是同一台機器、沒有共用檔案系統——如果檔案內容要先讓 Claude
讀出來、經過文字生成重新組成 base64 字串再塞進工具參數,大檔案(實測約 100~120KB 的截
圖)在這個來回搬運過程中會壞掉、byte 數對不上(見 #26221 的踩雷紀錄:重建出的 base64 在
第 2357 字元就已經跟原始檔案不一致)。壞損來源是「經過文字生成搬運」本身,換成別種編碼
(hex 等)一樣會壞,不是 base64 這個格式的問題。

真正可靠的做法是完全繞開 Claude 的文字生成,讓 curl 直接從磁碟讀檔上傳。這個 plugin 已經
隨附了上傳腳本,就放在本 skill 目錄底下的 `scripts/upload_attachment.sh`——skill 被載入時
系統會顯示「Base directory for this skill」,腳本的完整路徑就是那個目錄加上
`scripts/upload_attachment.sh`:

```bash
<Base directory for this skill>/scripts/upload_attachment.sh <本機檔案路徑> [檔名,預設用路徑檔名]
```

成功時腳本會印出一行 JSON 到 stdout,例如:

```json
{"token":"1234.abcd1234","id":1234,"filename":"screenshot.png","content_type":"application/octet-stream","filesize":632400}
```

把裡面的 `token`/`filename`/`content_type` 組成 `[{token, filename, content_type}]`,帶進
`create_issue`/`update_issue` 的 `uploads` 參數即可完成附加——token 只是一個短字串,透過
工具參數傳遞沒有壞損風險。如果腳本結束碼非零並在 stderr 給出錯誤訊息(檔案不存在、
`REDMINE_API_KEY` 沒設定、Redmine 回傳非 201 等),照 stderr 訊息處理,不要自己另外猜原
因,也不要改用 `content_base64` 繞過去。

### 寫入 Redmine 的基本準則(規格: "#26311":https://redmine.nineder.com/issues/26311 )

不管是透過 `create_issue`/`update_issue` 寫 description,還是用 `notes` 加一則 journal,
都要遵守下面的準則(完整規格與版本記錄見
"#26311":https://redmine.nineder.com/issues/26311 ,以那張議題的 Description 為準):

1. **結論與過程分離**:結論寫在 issue 的 Description(隨時維持最新狀態),過程、討論、
   試錯記錄留在 journal Note——讓人不用讀完整串 Note 也能掌握現狀。
2. **超連結前後都要留一個半形空白**,不能直接緊貼中文字或其他文字。Textile 的超連結語法
   (`"文字":https://...`)緊貼在中文字後面時,Redmine 介面轉譯容易把連結範圍跟旁邊的字混
   在一起、造成顯示錯亂——「參考"#26135":https://...這張」要改成「參考 "#26135":https://...
   這張」(前後各補一個半形空白;如果本來就是行首/行尾或已經有空白,就不用重複加)。
3. **防同時寫入互蓋**:要更新一張既有議題的 Description 之前,必須先呼叫 `get_issue` 重新
   讀取最後版本、以最新內容為基礎合併這次的修改,然後**立刻**呼叫 `update_issue` 寫回——
   把「讀」跟「寫」之間的間隔壓到最短,降低多個 session 同時編輯同一張議題時互相覆蓋的
   機率。不要拿幾分鐘前、甚至更早讀到的舊內容直接改一改就寫回去。
4. **更新後驗證**:`update_issue` 完成後要再 `get_issue` 確認結果——實測發生過只更新
   description 卻讓 status/done_ratio 被意外翻動的情況,不能只看呼叫成功就結束。
5. **Textile 表格儲存格內沒有任何跳脫符號能換行**(字面的 `\n`、`<br>` 都只會顯示成原始文
   字,`*` 條列符號也不會變成清單):儲存格內容兩項以上時,改用數字編號(`1.` `2.` `3.`,
   子項 `2-1.` `2-2.`)配合**真正的換行字元**分隔(實測記錄見 #26135)。
6. **程式碼區塊(三個反引號包起來的 code fence)超過 10 行時,改用 Redmine 內建的
   `{{collapse(標題文字)...}}` macro 包起來**,預設收合、標題顯示簡短說明,讀者需要看細節
   才展開。10 行以內維持原本三個反引號的寫法即可。
7. **journal Note 的文字描述超過 4 行時,先整理成幾行重點摘要放在 Note 開頭,完整過程/
   細節改用 `{{collapse(標題文字)...}}` macro 包起來預設收合**——讓人掃過 Note 串就能抓到
   每一則的重點,需要細節再展開。
8. **API 角色權限上限**:議題狀態透過 API 最多只能推到 Resolved,最終的 Closed 需要使用
   者自己在網頁上操作;這個站台的 done_ratio 由狀態自動計算,手動設定無效——遇到「幫我
   關掉議題」的需求,推到 Resolved 之後老實跟使用者說最後一步要他自己點。

如果 `/redmine` 被呼叫時**完全沒有帶任何任務**(只有指令本身,後面什麼都沒有),不要憑空
猜測要執行什麼操作。只要回報連線狀態——正常運作,或是需要設定——如果狀態正常,就順便列
出可用的工具,讓使用者知道下次可以怎麼問。
