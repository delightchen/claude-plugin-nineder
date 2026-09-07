# Redmine Plugin（分發模型 v2：bootstrap）

耐德科技組織內部的 Claude Plugin。**v4.0.0 起本 plugin 不攜帶任何內容 skill**（v4.0.3 起有一個開機用的 `/redmine:setup` 指令） —— 公司 Skill 的
內容正本是 Redmine Skill 票的附檔，由 `/nineder-skill` 同步到成員機器的
`~/.claude/skills/`。plugin 只負責三件事：把同步器種下去、維護 UserPromptSubmit hook、
每次 session 開始時觸發一次同步。

規範正本：[#26309](https://redmine.nineder.com/issues/26309) 附加資訊【分發模型 v2】。

## 安裝（組織成員）

```bash
claude plugin marketplace add https://gitlab.nineder.com/nineder/claude/plugin.git
claude plugin install redmine@nineder
```

裝完**整個重啟** Claude Code（plugin 在行程啟動時載入，桌面版沒有 reload 指令），然後在
對話裡輸入：

```
/redmine:setup
```

（v4.0.3 起提供。等效的手動做法是自己執行 `bash ~/.claude/plugins/marketplaces/nineder/redmine/scripts/bootstrap.sh`。）

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
[耐德集團工作區 Wiki「Claude Code 新機器安裝」](https://redmine.nineder.com/projects/website_managfc/wiki/Claude_Code_%E6%96%B0%E6%A9%9F%E5%99%A8%E5%AE%89%E8%A3%9D)。

repo 是 private，第一次 clone 需要公司 GitLab（gitlab.nineder.com）帳號憑證。

## 從 v3.x 升上來

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
- `commands/setup.md` — `/redmine:setup`，v4.0.3 起。內容是「執行一次 bootstrap.sh 並轉述
  結果，然後接手 `nineder-skill` 跑機器健檢」。**存在的理由**：桌面版不執行 plugin 宣告的
  hook，但**照常載入 plugin 的 commands 與 skills**，所以這是唯一能讓純桌面版使用者「打一個
  指令」就完成開機設定的路徑——不必貼一長串 bash 路徑，也不必開終端機。
  這是 plugin 內唯一的 command，**刻意不做成 skill**：它是一次性的操作入口，不是知識，
  而且不會與 `~/.claude/skills/` 的任何目錄同名打對台
- `hooks/hooks.json` — 只宣告 SessionStart，指向 `scripts/bootstrap.sh`。刻意**不**宣告
  UserPromptSubmit：桌面版不執行 plugin 宣告的該 event，而 CLI 會，兩邊都宣告會重複注入。
  （桌面版連 SessionStart 也不執行，所以這個宣告實際上只服務 CLI；桌面版靠 bootstrap 寫進
  settings.json 的那條）
- `scripts/bootstrap.sh` — SessionStart 唯一入口，依序做四件事：
  1. `~/.claude/skills/nineder-skill/` **不存在**時從 `seed/` 種一份（存在就完全不碰 ——
     plugin 永遠不覆寫已安裝的版本，升版一律走 Redmine 附檔）
  2. 冪等維護 `~/.claude/settings.json` 的 **UserPromptSubmit 與 SessionStart 兩條**
     （後者指向 bootstrap.sh 自己——這是純桌面版機器唯一跑得到 bootstrap 的路徑）
  3. 移除 v3.x 留下的 `~/.claude/commands/` 指標檔（redmine 四個＋google 兩個，只刪內容
     確實是指標檔的）
  4. 呼叫 `~/.claude/skills/nineder-skill/scripts/sync.sh --auto`

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
- `seed/nineder-skill/` — 同步器的種子副本（`SKILL.md` ＋ `scripts/sync.sh`）。**刻意不放在
  `skills/` 底下**，這樣 plugin 機制不會把它當 skill 載入，成員機器上就只會有
  `~/.claude/skills/nineder-skill/` 一份。種子只在全新機器用得到，之後由 Redmine 附檔
  （[#26915](https://redmine.nineder.com/issues/26915)）自我升版。

## 改 skill 內容不必動這個 repo

| 改什麼 | 走哪條路 |
| --- | --- |
| 任何 skill 的內容 | 改 Redmine Skill 票的附檔＋推票頭「現行版本」。成員端下次開對話自動同步，**不必發 plugin、不必重啟** |
| `bootstrap.sh`、`issue_context.sh`、`hooks.json`、`commands/setup.md`、`seed/` | 走本 repo 的發佈流程，成員要先更新再完整重啟 |

## 規格治理（單一事實來源）

改任何行為之前先改規格議題，再同步檔案：

- [#26309](https://redmine.nineder.com/issues/26309) — 開發準則與【分發模型 v2】
- [#26559](https://redmine.nineder.com/issues/26559) — hook 規格（v3.0 起 SessionStart 由 bootstrap.sh 承載）
- [#26915](https://redmine.nineder.com/issues/26915) — `/nineder-skill` 同步器
- [#26825](https://redmine.nineder.com/issues/26825) — plugin 發佈規範與常見錯誤
- [#26311](https://redmine.nineder.com/issues/26311) — `/redmine` 基本寫入準則（skill 內容已移至該票附檔）

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
