# Redmine Plugin（分發模型 v2：bootstrap）

耐德科技組織內部的 Claude Plugin。**v4.0.0 起本 plugin 不攜帶任何內容 skill**（v4.0.3 起有一個開機用的 `/redmine:setup` 指令） —— 公司 Skill 的
內容正本是 Redmine Skill 票的附檔，由 `/nineder-skill` 同步到成員機器的
`~/.claude/skills/`。plugin 只負責三件事：把同步器種下去、維護 settings 層的 hook
（UserPromptSubmit、SessionStart、v4.0.7 起加上 PreToolUse 自動夾帳）、每次 session 開始時觸發一次同步。

規範正本：[#26309](https://redmine.nineder.com/issues/26309) 附加資訊【分發模型 v2】。

## 安裝

**組織成員不必安裝。** plugin 在 claude.ai Organization Settings 設為 `User access: Required`，
桌面版開啟時自動載入。成員只要**整個重啟** Claude Code，然後在對話裡輸入：

```
/redmine:setup
```

（v4.0.3 起提供；v4.0.4 起會自己找 plugin 落地位置，不再寫死路徑。）

維護者若要在 CLI 端測試同一份程式碼，另有一條 marketplace 路徑：

```bash
claude plugin marketplace add https://gitlab.nineder.com/nineder/claude/plugin.git
claude plugin install redmine@nineder
```

**這條路不要給一般成員**——repo 是 private，成員沒有讀取權，`marketplace add` 會失敗。
兩套機制互不可見，詳見「兩條派發來源」一節。

**這一步在桌面版不能省。** Claude Code 桌面版**不執行 plugin 宣告的任何 hook**——
UserPromptSubmit 是已知的 parity gap（[#26559](https://redmine.nineder.com/issues/26559) v2.2、
[anthropics/claude-code#45514](https://github.com/anthropics/claude-code/issues/45514)），
SessionStart 於 2026-09-07 實測確認同樣不執行。而 `~/.claude/settings.json` 宣告的 hook
兩邊都有效，所以上面這一行的用途就是**把兩條 settings 條目寫進去**（UserPromptSubmit 指向
issue_context.sh、SessionStart 指向 bootstrap.sh 自己）。跑過這一次之後就全自動了——
之後每次開新對話都由 settings 層的 SessionStart 觸發同步。

（CLI 使用者跑 `claude` 時 plugin 的 SessionStart 會執行，等於自動完成這一步，但手動跑一次
也不會有副作用——本腳本完全冪等。）

接著開一個新對話輸入 `/nineder-skill`，它會帶你走完「機器健檢七格」：Redmine API key 鑰匙檔、
兩個 MCP 的註冊與登入、Skill 同步、Google 帳號綁定。人的操作手冊在
[耐德集團工作區 Wiki「Claude Code 新機器安裝」](https://redmine.nineder.com/projects/47/wiki/Claude_Code_%E6%96%B0%E6%A9%9F%E5%99%A8%E5%AE%89%E8%A3%9D)。

repo 是 private，第一次 clone 需要公司 GitLab（gitlab.nineder.com）帳號憑證。

## 從 v3.x 升上來

組織派發的機器（多數成員）只要**整個重啟**，再輸入一次 `/redmine:setup`。
新版何時到那台機器由組織端控制——若 Organization Settings 開著版本核准，新版會卡在
「to review」直到管理員核准，成員端不論重啟幾次都拿不到。

維護者的 CLI 端：

```bash
claude plugin marketplace update nineder
claude plugin update redmine@nineder
```

然後**整個重啟**，再輸入一次 `/redmine:setup`（同樣不能省，理由見安裝段）。順序不能
反 —— 先更新、再重啟；反了等於重啟時載入舊版
（[#26825](https://redmine.nineder.com/issues/26825) 常見錯誤表）。

升上來之後有三個可見的變化：

1. 原本由 plugin 提供的五支 skill 改由 `~/.claude/skills/` 提供，內容相同、版本可能更新
2. `~/.claude/commands/` 底下六個舊的裸名指標檔會被自動移除（redmine 四個＋google 兩個；
   skill 裝在使用者層級本來就以裸名觸發，指標檔已無用途）；你自己寫的同名 command 不會被動
3. 第一次開對話會多一行提示，請你輸入 `/nineder-skill` 完成設定

google plugin 已於本版整支廢除，其兩支 skill 改由 Skill 票
[#26934](https://redmine.nineder.com/issues/26934)、[#26935](https://redmine.nineder.com/issues/26935)
承載，同樣由 `/nineder-skill` 自動安裝。

## 結構

- `.claude-plugin/plugin.json` — plugin 資訊清單（**每次發佈都要把 version 往上推**，否則
  客戶端的更新檢查會跳過這一版）
- `commands/setup.md` — `/redmine:setup`，v4.0.3 起。內容是「找到並執行一次 bootstrap.sh 並
  轉述結果，然後接手 `nineder-skill` 跑機器健檢」。v4.0.4 起帶一段搜尋（本 session 的
  `CLAUDE_PLUGIN_ROOT` → CLI marketplace → 組織派發目錄 → 穩定副本），不再寫死路徑。**存在的理由**：桌面版不執行 plugin 宣告的
  hook，但**照常載入 plugin 的 commands 與 skills**，所以這是唯一能讓純桌面版使用者「打一個
  指令」就完成開機設定的路徑——不必貼一長串 bash 路徑，也不必開終端機。
  這是 plugin 內唯一的 command，**刻意不做成 skill**：它是一次性的操作入口，不是知識，
  而且不會與 `~/.claude/skills/` 的任何目錄同名打對台
- `hooks/hooks.json` — 只宣告 SessionStart，指向 `scripts/bootstrap.sh`。刻意**不**宣告
  UserPromptSubmit：桌面版不執行 plugin 宣告的該 event，而 CLI 會，兩邊都宣告會重複注入。
  （桌面版連 SessionStart 也不執行，所以這個宣告實際上只服務 CLI；桌面版靠 bootstrap 寫進
  settings.json 的那條）
- `scripts/bootstrap.sh` — SessionStart 唯一入口，依序做六件事。**目前只在
  macOS／Linux／WSL 上驗證過**（bash 腳本，原生 Windows 的殼層執行不了；即使能
  執行，`collect.py` 以外的部分也從沒在 Windows 上測過）：
  0. **版本自報**（4.0.9 新增）：印一行 `nineder-skill：目前 Redmine plugin 版本
     vX.Y.Z（版號日期）`，讀 `.claude-plugin/plugin.json` 的 `version`／`versionDate`。
     不管其餘步驟有沒有變動都印，因為它就是給人核對「這台機器是不是最新版」用的——
     這件事在導入版本自報之前只能靠人工比對 `plugin.json` 內容或 commit hash，
     在這之前的一次排查裡花了不少時間
  1. 把自己、`issue_context.sh`、`ai_usage_inline.py`、`collect.py`、`daily_trigger.py`、
     `resolved_trigger.py` 複製到 `~/.claude/nineder/bin/`（內容有變才複製）——settings
     的 hook 一律指向這份副本，理由見「兩條派發來源」
  2. `~/.claude/skills/nineder-skill/` **不存在**時從 `seed/` 種一份（存在就完全不碰 ——
     plugin 永遠不覆寫已安裝的版本，升版一律走 Redmine 附檔）。從穩定副本被呼叫時看不到
     `seed/`，此時印一行「請輸入 `/redmine:setup`」而不是靜默
  3. 冪等維護 `~/.claude/settings.json` 的 **UserPromptSubmit、SessionStart（bootstrap.sh
     自己＋每日用量排程 daily_trigger.py）、PreToolUse 的 create_issue／update_issue 自動
     夾帳，以及 PostToolUse 的議題轉 Resolved 排程**（PreToolUse 見 v4.0.7、
     [#27113](https://redmine.nineder.com/issues/27113)；SessionStart 第二條與 PostToolUse 見 v4.0.8、
     [#27090](https://redmine.nineder.com/issues/27090)），全部指向 `~/.claude/nineder/bin/`。舊版寫進去的
     marketplace 路徑條目會一併換掉，不會變成重複條目；有 matcher 的條目連 matcher 一起
     比對，不會互相清掉。**已知殘留**：在 4.0.8 之前手動把 `daily_trigger.py`／
     `resolved_trigger.py` 加進自己 `settings.json` 的機器，舊的手動條目不會被自動辨識、
     也不會被清掉，會跟新裝的穩定路徑版本並存，變成同一支腳本被觸發兩次——不會出錯
     （`collect.py` 的鎖會擋下其中一次），但要手動清舊的那條才乾淨（維護者自己這台已於
     2026-09-16 手動清過）
  4. 移除 v3.x 留下的 `~/.claude/commands/` 指標檔（redmine 四個＋google 兩個，只刪內容
     確實是指標檔的）
  5. 呼叫 `~/.claude/skills/nineder-skill/scripts/sync.sh --auto`

  兩條界線：**不碰 `~/.claude.json`、不做 `claude mcp add`**（主設定檔併發寫有風險，且 hook
  環境未必找得到 `claude` 指令；MCP 註冊交給 `/nineder-skill` 在對話裡做）。任何錯誤都
  結束碼 0，絕不阻擋 session 開始。
- `scripts/issue_context.sh` — UserPromptSubmit hook（[#26559](https://redmine.nineder.com/issues/26559)、
  [#26851](https://redmine.nineder.com/issues/26851)）：訊息裡出現 Redmine 議題編號
  （`#26311` 或議題網址）時注入編號與連結對照表，加上「回覆中編號一律輸出為超連結」（準則
  第 16 條）與「先把 session 改名為 `#編號 subject`」（第 21 條）兩條提醒；**全新 session 的
  第一則訊息**含編號時改名是無條件的。訊息裡出現公司 GitLab repo 短路徑（例如
  `/charleslu/slap`，第一段命中內建 namespace 清單）時同樣注入 `gitlab.nineder.com` 連結
  候選，由 Claude 依上下文確認真的是 repo 才輸出（第 19 條，寧可漏連不可錯連；`/Users/...`
  這類檔案路徑不會觸發）。不開啟任何頁面；預設啟用，設 `REDMINE_ISSUE_CONTEXT=0` 停用；
  fail-open。
- `scripts/ai_usage_inline.py` — PreToolUse hook（[#27113](https://redmine.nineder.com/issues/27113)）：MCP 呼叫
  `create_issue`／`update_issue` 之前，自動跑同目錄下的 `collect.py --pending`，把結果塞進
  `ai_usage` 參數，取代「記得先跑 --pending 再貼參數」——正式站實測 1,287 次 MCP 寫入只有
  16 次帶了用量，正是那個「記得」失效的證據。已經自己帶 `ai_usage` 的呼叫不覆蓋；找不到
  `collect.py`、逾時、任何例外，或採集器回 `pending:false`，一律安靜放行原始寫入，不擋下
  使用者的寫入、不補零。
- `scripts/collect.py` — AI 用量採集器本體，`ai_usage_inline.py` 用 subprocess 呼叫的那一支。
  與 GitLab `nineder/redmine/plugin/issue_provenance` 的 `collector/collect.py` 是同一份邏輯
  （非公開發行版本，此份保留內部端點與預設值），改動需要在兩邊同步，但**不必為此發 plugin
  新版** —— 只有 `ai_usage_inline.py` 找不到 `collect.py` 時的行為（fail-open）跟 plugin 有關；
  `collect.py` 本身的計算邏輯改動走 issue_provenance 那個 repo 自己的部署流程，plugin 這份只是
  搭 PreToolUse 便車的最新副本，下次 plugin 發版時才會更新
- `scripts/daily_trigger.py` — SessionStart hook（[#27090](https://redmine.nineder.com/issues/27090)）：每天第一個 session
  啟動時，背景補跑一次同目錄下的 `collect.py`。只負責「今天觸發過一次」的判斷（一個記
  日期的標記檔），失敗與否交給 `collect.py` 自己的執行紀錄；fail-open，找不到
  `collect.py` 就什麼都不做，永遠不擋下 session 開始。
- `scripts/resolved_trigger.py` — PostToolUse hook（[#27090](https://redmine.nineder.com/issues/27090)，只攔
  `update_issue`）：議題被推到 Resolved 的當下，背景補跑一次 `collect.py`，把還沒歸帳
  的用量收一次。2026-09-16 之前這支解析 `tool_response` 的邏輯跟實際格式不符，兩次真實
  觸發全部誤判為沒有 usage（已修好並用真實案例重放驗證，見 `test_resolved_trigger.py`）。
- `scripts/collect.py` 的鎖檔機制 2026-09-16 前用 `fcntl.flock`——**Windows 完全沒有
  這個模組**，import 那一行會讓整支程式在原生 Windows 上直接當掉。已經改成
  `os.O_CREAT|O_EXCL` 的原子建檔鎖（POSIX／Windows 語意一致），但這只解決了
  `collect.py` 這一層；`bootstrap.sh` 本身還是純 bash，原生 Windows 目前依然完全沒有
  處理，這件事還沒有票追蹤
- `seed/nineder-skill/` — 同步器的種子副本（`SKILL.md` ＋ `scripts/sync.sh`）。**刻意不放在
  `skills/` 底下**，這樣 plugin 機制不會把它當 skill 載入，成員機器上就只會有
  `~/.claude/skills/nineder-skill/` 一份。種子只在全新機器用得到，之後由 Redmine 附檔
  （[#26915](https://redmine.nineder.com/issues/26915)）自我升版。

## 改 skill 內容不必動這個 repo

| 改什麼 | 走哪條路 |
| --- | --- |
| 任何 skill 的內容 | 改 Redmine Skill 票的附檔＋推票頭「現行版本」。成員端下次開對話自動同步，**不必發 plugin、不必重啟** |
| `collect.py` 的計算邏輯（採集器本體） | 走 GitLab `nineder/redmine/plugin/issue_provenance` 自己的部署流程；這裡的副本只在下次 plugin 發版時才會跟著更新，不必為了同步這一份而特地發版 |
| `bootstrap.sh`、`issue_context.sh`、`ai_usage_inline.py`、`daily_trigger.py`、`resolved_trigger.py`、`hooks.json`、`commands/setup.md`、`seed/` | 走本 repo 的發佈流程，成員要先更新再完整重啟 |

## 規格治理（單一事實來源）

改任何行為之前先改規格議題，再同步檔案：

- [#26309](https://redmine.nineder.com/issues/26309) — 開發準則與【分發模型 v2】
- [#26559](https://redmine.nineder.com/issues/26559) — hook 規格（v3.0 起 SessionStart 由 bootstrap.sh 承載）
- [#26915](https://redmine.nineder.com/issues/26915) — `/nineder-skill` 同步器
- [#26825](https://redmine.nineder.com/issues/26825) — plugin 發佈規範與常見錯誤
- [#26311](https://redmine.nineder.com/issues/26311) — `/redmine` 基本寫入準則（skill 內容已移至該票附檔）

## 兩條派發來源（4.0.4 的成因）

| 來源 | 落地位置 | `claude plugin list` 看得到嗎 |
| --- | --- | --- |
| 組織派發（多數成員） | `~/Library/Application Support/Claude/local-agent-mode-sessions/<session-id>/<sub-id>/rpm/plugin_<id>/` | **看不到** |
| CLI marketplace（維護者） | `~/.claude/plugins/marketplaces/nineder/redmine/` | 看得到 |

組織派發的路徑**含 session id，每次開對話都會變**，所以：

1. **任何寫進 `~/.claude/settings.json` 的 plugin 絕對路徑，下次開對話就失效。**
   4.0.3 以前寫死的是 CLI marketplace 路徑，在組織派發的機器上那個目錄根本不存在——
   兩條 hook 都指向找不到的檔案，fail-open 不報錯，等於完全沒作用
   （[#26915](https://redmine.nineder.com/issues/26915) note-27，張穎秦 jacob.chang 回報）
2. 也不能改成「由 `CLAUDE_PLUGIN_ROOT` 推導」——那個值只在當下這個 session 正確，
   寫進 settings 一樣過期

所以 4.0.4 的解法是**穩定副本**：bootstrap 每次先把自己與 `issue_context.sh` 複製到
`~/.claude/nineder/bin/`，settings 條目只認這個位置。兩種派發方式都成立，路徑永久有效，
而 plugin 升版時新版 bootstrap（由 plugin 的 SessionStart 或 `/redmine:setup` 觸發）會自動
把副本更新掉。

判斷成員機器上的版本請一律用「`/redmine:setup` 打不打得出來」，**不要用 `claude plugin details`**
——組織派發的 plugin 不在 CLI 的視野裡，會把能用的機器判成「沒裝」。

## 發佈與鏡像

主要開發 remote 是公司 GitLab（host `gitlab.nineder.com`）。GitLab 端設定 **push mirroring**
到 GitHub private repo `delightchen/claude-plugin-nineder`（供 claude.ai Organization Settings
的 GitHub App 派發）。**維護者只推 GitLab**，GitHub 鏡像自動同步 —— 但發佈完要用 SHA 比對
確認，不要看鏡像狀態欄位（[#26825](https://redmine.nineder.com/issues/26825) 第五段）。

`main` 為保護分支。流程：改檔 → `plugin.json` version 往上推 → push 到 `release/<版本>`
分支 → 開 MR → merge 進 main。

歷史：v3.x 以前 plugin 直接攜帶五支 skill，改一行 skill 就要發版並請全公司重啟；v4.0.0 起
內容改由 Redmine 附檔承載（[#26937](https://redmine.nineder.com/issues/26937) 為切換記錄）。
更早之前是「單一 `redmine.skill` 上傳 Organization Settings ＋ 本機 heredoc 同步」
（[#26137](https://redmine.nineder.com/issues/26137) 鐵律時代）。
