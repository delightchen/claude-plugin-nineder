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
(`https://mcp.nineder.com/redmine/mcp`),每個人都用自己的 Redmine API key 個別驗證身份。
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

### 已註冊舊的 `redmine`(舊網址)

2026 年 8 月起,Redmine MCP 搬到公司統一的 gateway `mcp.nineder.com`,伺服器名稱也改為
`nineder-redmine`(跟 `nineder-google` 一致)。舊的 `mcp.redmine.nineder.com` 仍在運行,
但已進入淘汰階段。

用 `claude mcp list` 檢查,如果看到名為 `redmine` 且指向 `mcp.redmine.nineder.com` 的項目,
那是舊的。**新舊可以並存**,名稱不同不會互相干擾,所以先照下面「尚未設定」的步驟把
`nineder-redmine` 加好、登入、確認能用,**確認新的沒問題之後**再移除舊的:

```bash
claude mcp remove redmine --scope user
```

不要先移除舊的再加新的——萬一新的有問題,中間會有一段完全不能用的空窗。

### 尚未設定

自己透過 Bash 執行下面這行指令——它只是註冊伺服器位址,不會驗證任何人的身份,所以可以
放心直接執行,不用先問過使用者。**一定要加上 `--scope user`**——如果沒加,
`claude mcp add` 預設會用 `local` scope,那樣只會把伺服器註冊在「你現在剛好待著的那一個
專案資料夾」裡,不會套用到整台機器。這個預設值正是造成「`/redmine` 在某些專案資料夾能用、
其他資料夾不能用」的真正原因——從來就不是同步/傳播的問題,而是 scope 設錯了。

```bash
claude mcp add --transport http --scope user nineder-redmine https://mcp.nineder.com/redmine/mcp
```

如果這台機器上 `nineder-redmine` 已經註冊過,但只是用 `local` scope(用 `claude mcp list` 檢查——
如果只有在特定幾個專案資料夾才能用,原因就是這個),先把那些殘留的 local 註冊清掉,免得
留著造成混淆,再用 `user` scope 重新加回去:

```bash
claude mcp remove nineder-redmine --scope local
claude mcp add --transport http --scope user nineder-redmine https://mcp.nineder.com/redmine/mcp
```

接著要老實跟使用者說,還差最後一步需要他親自動手,因為那是一個互動式的瀏覽器登入,你沒
辦法代替他完成:

```bash
claude mcp login nineder-redmine
```

先跟他說清楚接下來會發生什麼事,才不會嚇到他:這個指令會開啟瀏覽器,連到 Redmine MCP
伺服器自己的登入頁面,使用者要在那裡貼上自己**個人的 Redmine API access key**(在 Redmine
→ 我的帳戶 → API access key,頁面右上角可以找到)。完成後,產生的存取權杖只會存在這台
機器上。要明確跟他說這是「以機器為單位」的——如果他也在其他電腦上用 Claude,每一台都需
要各自單獨執行一次 `claude mcp login nineder-redmine`,而且每一台都可以用不同的 Redmine 身份,
如果他想要的話。

如果這裡沒有瀏覽器可用(例如透過 SSH 連線的情況),改給他這個指令:

```bash
claude mcp login nineder-redmine --no-browser
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
claude mcp login nineder-redmine
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
案。這個 MCP server 是部署在公司 VM 上的 remote MCP(`https://mcp.nineder.com/redmine`),
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
6. **程式碼/可複製內容一律用 `<pre>` 區塊包起來、收合、並在外面下結論**:不管是寫
   description 還是 journal Note,只要內容不在 Textile 表格儲存格內,而且屬於程式碼、指令、
   設定檔、log、API payload 等跟程式相關、或讀者可能整段複製貼上的東西,一律照下面的方式
   寫——不要再用三個反引號的 code fence,也不分行數多寡(這條取代了舊的「超過 10 行才收
   合」門檻):
   - 語言在 Redmine 內建清單內(`css` `diff` `go` `groovy` `html` `java` `javascript`
     `objc` `perl` `php` `python` `r` `ruby` `sass` `scala` `shell` `sql` `swift` `xml`
     `yaml`)→ 用 `<pre><code class="python">...</code></pre>`(class 值填語言名稱)。
   - 不在清單內(`ini`、`conf`、`Dockerfile`、純文字輸出、Textile 原始碼、混合內容)→ 只用
     `<pre>...</pre>`,不要硬套一個不存在的 class。
   - 每個 `<pre>` 區塊都要再用 `{{collapse(標題文字)...}}` macro 包起來預設收合,標題寫簡短
     說明(例如「部署指令:重啟 unicorn」「錯誤 log:nginx 502」)。
   - 收合外面要用一到兩句話下結論——這段在做什麼、結果或重點是什麼——讓人不展開也能掌握
     全貌,需要複製時再展開。
   - 表格儲存格內不適用:Textile 表格內無法正常呈現 `<pre>` 區塊,要附程式碼時改放到表格外
     另開一個收合區塊。
7. **寫進 Redmine 的內容裡,行內程式碼標記 `@...@` 內不得出現角括號標籤**:Textile 的 `@`
   語法本身就會產生 `<code>` 標籤,內容再帶一個 `<code>`/`<pre>` 會變成沒有收尾的巢狀標籤,
   **從那一行起整份文件的 HTML 結構全垮**——後面所有 Textile 表格都不會被解析成表格,畫面
   上只剩一堆字面的 `|={background-color: ...}.` 語法,而且 Redmine 不會給任何錯誤提示。同
   理,把 `@` 連寫兩個(想表示 `@` 符號本身)會讓分隔符數量變成奇數,效果一樣。要說明 HTML
   標籤時一律寫成「code 標籤」「b 標籤」這類文字敘述;真的需要展示角括號原始碼,依第 6 條放
   進收合的 `<pre>` 區塊。(實例:#26537 就是在 Feature 模板的儲存格裡用 `@` 包住角括號形式
   的 code 標籤,整張單兩個表格全部沒被解析。)
8. **含表格的內容存檔前必須先驗證排版**:凡是要寫入含 Textile 表格的 description(例如
   Feature 模板的 As-a/Given-When-Then 表格),送出前先自己檢查兩件事——每一行的 `@` 數量
   必須成對,而且成對區間內不含 `<`。有主機權限的 session 再進一步用 Redmine 自己的格式轉
   換器實際試算:把內容寫成檔案,在 Redmine 應用程式目錄下以 redmine 使用者跑 `rails
   runner`,將內容丟進 `Redmine::WikiFormatting.to_html(Setting.text_formatting, 內容)`,
   檢查產生的 HTML 裡 `<table` 出現次數等於預期表格數、`|={background` 殘留數為 0。排版壞掉
   時只 render 前 k 行、k 從 1 遞增,就能定位到是哪一行出問題。
9. **journal Note 的文字描述超過 4 行時,先整理成幾行重點摘要放在 Note 開頭,完整過程/
   細節改用 `{{collapse(標題文字)...}}` macro 包起來預設收合**——讓人掃過 Note 串就能抓到
   每一則的重點,需要細節再展開。
10. **圖片附件要內嵌顯示並收合**:上傳圖片/桌面截圖到 Redmine 後(用上面的
    upload_attachment.sh 拿 token、掛進 `uploads` 參數),不能只留在附件列表——要在
    description 或 Note 內文用 Redmine 行內圖片語法把檔名包起來(`!檔名.png!`,動圖
    `!檔名.gif!` 同理),並把這行圖片語法放進 `{{collapse(標題文字)...}}` macro 裡、標題給
    簡短說明文字(例如「畫面截圖:登入錯誤訊息」),預設收合、點標題才展開圖片——大圖不
    佔版面,讀者也知道收合裡是什麼圖。
11. **`precedes`/`follows` 會自動改日期,不要拿來表示「相關」**:建立 `precedes`/`follows`
    關聯時,Redmine 會自動重排後續議題的 start_date/due_date——開始日被推到前置議題到期日
    的隔天,到期日再依原本工期往後平移,整個過程沒有任何提示(實例:#26537 原本填
    2026-08-15/2026-10-31,設了 `follows #26534` 之後立刻被改成 2026-10-01/2026-12-17)。
    只是要表達「這兩張單有關」或「這是後續工作」時,一律用 `relates`;只有真的要表達排程上
    的先後順序、而且接受日期被自動計算,才用 `precedes`/`follows`。已經誤設的話,刪掉關聯
    **不會**把日期還原,必須另外用 `update_issue` 把 start_date/due_date 改回原值。
12. **API 角色權限上限**:議題狀態透過 API 最多只能推到 Resolved,最終的 Closed 需要使用
    者自己在網頁上操作;這個站台的 done_ratio 由狀態自動計算,手動設定無效——遇到「幫我
    關掉議題」的需求,推到 Resolved 之後老實跟使用者說最後一步要他自己點。
13. **公司 GitLab 連結一律寫 `gitlab.nineder.com`**(規格: "#26311":https://redmine.nineder.com/issues/26311 第 15 條):
    寫進 Redmine 的任何公司 GitLab 連結,**網址與連結文字都不得出現 `gitlabnew.nineder.com`**
    ——即使本機 repo 的 `git remote` 目前仍指向 gitlabnew 也一樣。兩個例外:(1) 外部第三方
    的 github.com、gitlab.com 等,照原網址寫;(2) 確實在指稱 gitlabnew 那台主機本身(遷移
    作業、SSH 連上去操作)時是主機名而非連結,可以保留。
14. **回覆使用者時,議題編號一律輸出為超連結**(規格: "#26311":https://redmine.nineder.com/issues/26311 第 16 條):
    在對話中提到任何 Redmine 議題編號時,一律輸出成指向
    `https://redmine.nineder.com/issues/編號` 的超連結,不要只留純文字編號。**使用者訊息中
    出現的編號同樣適用**——不論在句首、句中,或整句只有它,回覆時都要把該編號輸出成連結,
    讓對方不必自己複製編號、開瀏覽器、貼網址。本條規範的是對使用者的**回覆**,與第 2 條
    (寫進 Redmine 的內容裡超連結前後留空白)是不同場景,兩者並存不衝突。
    *點擊落點(2026-08-17 實測)*:Claude Code 桌面版**一般點擊**會把連結攔到內建的 Claude
    Browser pane,而該 pane 沒有 Redmine 登入 session、顯示的是登入頁;**按住 Cmd 再點擊**
    才會外開到系統預設瀏覽器。連結寫法(markdown、裸網址、角括號)完全不影響落點,把 Chrome
    設為系統預設也不改變一般點擊的行為。使用者回報開在登入頁時,直接提示改用 Cmd 加點擊。

如果 `/redmine` 被呼叫時**完全沒有帶任何任務**(只有指令本身,後面什麼都沒有),不要憑空
猜測要執行什麼操作。只要回報連線狀態——正常運作,或是需要設定——如果狀態正常,就順便列
出可用的工具,讓使用者知道下次可以怎麼問。
