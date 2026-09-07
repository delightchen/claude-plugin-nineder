---
name: nineder-skill
description: 當使用者輸入 `/nineder-skill`，或說「這台機器怎麼裝公司的 Skill」「幫我設定 Redmine／Google 連線」「公司有哪些 Skill 我還沒裝」「我的 Skill 是不是舊了」「新機器要怎麼開始」時使用。本 skill 是公司 Skill 的單一來源同步器與新機器的唯一安裝入口：跑「機器健檢七格」（Redmine API key 鑰匙檔、兩個 MCP 的註冊與登入、Skill 同步、Google 帳號綁定），缺哪格補哪格；耐德集團工作區已核可（Resolved）的 Skill 由它自動裝進 ~/.claude/skills/ 並保持一致，其他專案的列出並給一列一支的安裝指令。只讀不寫 Redmine。要產出新 Skill 或升版是 /redmine-skill-create；要換綁 Google 帳號可直接用 /nineder-google-login。執行期間對使用者說的話一律繁體中文。
---

> 版本：v1.1（2026-09-06）｜方法正本：Redmine #26915

# 公司 Skill 同步與機器健檢 (`/nineder-skill`)

**無論使用者用什麼語言輸入，執行本 skill 期間對使用者說的每一句話都必須是繁體中文。**

本 skill 有兩個身份：**背景同步器**（plugin 的 SessionStart hook 每次開對話呼叫
`scripts/sync.sh --auto`，靜默，有變動才印一行）與**互動健檢**（使用者輸入 `/nineder-skill`
時由你執行下面的七格）。兩者共用同一支 `scripts/sync.sh`。規格正本在
"#26915":https://redmine.nineder.com/issues/26915 ，分發模型在
"#26309":https://redmine.nineder.com/issues/26309 附加資訊【分發模型 v2】。

回覆中任何 Redmine 議題編號一律輸出成指向 `https://redmine.nineder.com/issues/編號` 的超連結
（#26311 第 16 條）。人的操作手冊正本是耐德集團工作區 Wiki 頁「Claude Code 新機器安裝」
（ https://redmine.nineder.com/projects/website_managfc/wiki/Claude_Code_新機器安裝 ），
健檢報告的頁首要附這個連結。

## 三條硬規則

1. **只讀不寫 Redmine。** 不建票、不留言、不改票面、不碰附檔。
2. **鑰匙由使用者自己貼。** 不要請使用者把 API key 貼進對話，也不要自己讀出鑰匙檔的內容；
   給他一段指令，他在自己的終端機執行。你只驗「檔在不在、能不能通」。
3. **砍光同名只在一個地方、只在驗證通過之後。** `sync.sh` 已經把這件事做死：先下載、驗證
   （首行 frontmatter、檔內版本＝票頭版本）、才刪 `~/.claude/skills/名稱/` 再解開。你不要
   另外寫 `rm -rf`；非 47 集合的目錄、plugin cache、專案層 `.claude/skills/` 一律不動，
   同名影子只警告。

## 機器健檢七格（互動模式主流程，順序固定，缺哪格補哪格）

先跑一次盤點，拿到 JSON 再決定哪幾格要動：

```bash
bash ~/.claude/skills/nineder-skill/scripts/sync.sh --report
```

JSON 欄位：`key`（`source` 是 env／file／null、`valid`）、`mcp`（兩個 server 有沒有註冊在
`~/.claude.json`）、`auto`（47 每支：`name`、`local`、`remote`、`state` 為 ok／install／update／
ahead／dev／failed）、`others`（非 47 的 Resolved：`state` 與 `install_cmd`）、`shadows`、
`disabled`、`dev_skipped`、`failed`、`local_other`（本機非 47 集合的目錄）、`last_sync`、`wiki`。

| 格 | 檢查什麼 | 通過的長相 | 缺了怎麼修 |
| --- | --- | --- | --- |
| 1 | Redmine API key 鑰匙檔 | `key.valid` 為 true | 見下方「第 1 格」 |
| 2 | Redmine MCP 已註冊 | `mcp["nineder-redmine"]` 為 true，且工具清單有 `nineder-redmine` | `command -v claude` 有東西才執行：`claude mcp add --scope user --transport http nineder-redmine https://mcp.nineder.com/redmine/mcp` |
| 3 | Google MCP 已註冊 | `mcp["nineder-google"]` 為 true，且工具清單有 `nineder-google` | 同上：`claude mcp add --scope user --transport http nineder-google https://mcp.nineder.com/google/mcp` |
| 4 | Redmine MCP 已登入 | `get_current_user` 成功 | 請使用者執行 `claude mcp login nineder-redmine`；同意頁**貼剛才那一把 key** |
| 5 | Google MCP 已登入 | `google_whoami` 呼叫成功（不論 linked） | 請使用者執行 `claude mcp login nineder-google`；同意頁**貼同一把 key** |
| 6 | Skill 同步 | `auto` 裡沒有 install／update／failed | `bash ~/.claude/skills/nineder-skill/scripts/sync.sh --auto`，把印出的行轉述給使用者 |
| 7 | Google 帳號已綁定 | `google_whoami` 回 `linked` 為 true | 用 Skill tool 呼叫 `nineder-google-login` 接手；可跳過 |

**為什麼是這個順序**：第 4、5 格同意頁貼的就是第 1 格那把 key，所以第 1 格最先；第 7 格的
`/nineder-google-login` 是第 6 格從 Redmine 裝上來的，所以第 6 格在前。同一把 key 三處用——
不要讓使用者去「我的帳戶」拿三次。

### 第 1 格——鑰匙檔

`key.source` 為 null 或 `key.valid` 為 false 時，告訴使用者：到 Redmine 右上角「我的帳戶」→
右側「API 存取金鑰」→「顯示」，複製那一串，然後**在自己的終端機**把下面指令的中文字換成金鑰
執行（桌面版 bash 區塊有 Run 按鈕，但要先把中文字換掉再按）：

```bash
mkdir -p ~/.claude/nineder && chmod 700 ~/.claude/nineder && printf '%s\n' '把這一段換成你的 API 存取金鑰' > ~/.claude/nineder/redmine_api_key && chmod 600 ~/.claude/nineder/redmine_api_key && echo 鑰匙檔已建立
```

做完再跑一次 `--report` 看 `key.valid`。`valid` 為 false 而檔案存在＝貼錯或該帳號被鎖，
不要自己猜，請他重貼。**環境變數 `REDMINE_API_KEY` 也算**（CLI 使用者的舊習慣），但桌面版
的 hook 讀不到 shell 變數，所以新機器一律引導建鑰匙檔。

### 第 2、3 格——註冊 MCP

先 `command -v claude`。找不到＝這台沒裝 CLI（IDE 擴充或桌面版的 PATH 不一定有），不要假裝
成功，請使用者裝 CLI 或到終端機執行。找得到就用 Bash 直接執行 `claude mcp add`（這只是
寫設定，不用先問）。**一定要 `--scope user`**，不然只註冊在目前這個資料夾。

### 第 4、5 格——登入

`claude mcp login` 會開瀏覽器到 mcp.nineder.com 的同意頁，要貼 Redmine API key——就是第 1 格
那一把。請使用者自己執行（開瀏覽器、貼 key 都不是你該代做的事）；環境開不了瀏覽器就加
`--no-browser` 讓它印網址。登入完成後工具清單若還沒出現對應工具，請使用者**新開對話再輸入
`/nineder-skill`**，本 skill 會從缺的那一格接著做——不要在同一個 session 硬試。

### 第 6 格——同步

跑 `sync.sh --auto`（不是 `--report`），它只印有變動的行：已安裝／已更新／已停用／未安裝原因／
同名影子／其他專案可裝幾支。逐字轉述，再補一句「新開對話才會載入剛裝的 skill」。`--auto` 若
什麼都沒印＝已是最新。

### 第 7 格——Google 帳號綁定

第 6 格之後 `nineder-google-login` 應該已在 `~/.claude/skills/`。`google_whoami` 回
`linked` 為 false 時，用 Skill tool 呼叫 `nineder-google-login`，由它負責 `google_login`、把
授權頁開在右欄內建瀏覽器、等使用者完成、再 `google_whoami` 確認。它還沒被載入（同 session
剛裝）就請使用者新開對話後輸入 `/nineder-google-login`。使用者說不用 Google → 這格標
「未綁定（已跳過）」，之後報告照樣顯示，不催。

## 報告格式（互動模式最後一定要給）

頁首一行：Wiki 手冊連結 ＋ `last_sync.at`（沒有就寫「尚未同步過」）。然後三段：

**一、健檢七格**：一張表，每格一列，狀態用 ✅／❌／⏭（已跳過），❌ 的那格後面接一句
「怎麼修」。

**二、耐德集團工作區（自動）**：`auto` 每支一列——議題連結、名稱、本機版本、Redmine 版本、
狀態（最新／已更新／本機領先／開發中／失敗原因）。`disabled` 有東西時列出搬到哪裡。

**三、其他專案（人工）**：`others` 中 state 不是 ok 的，每支一列（議題連結、名稱、專案、
版本、本機版本），表後**每支一個 bash 區塊**放 `install_cmd`（桌面版一鍵 Run）：

```bash
~/.claude/skills/nineder-skill/scripts/sync.sh --install 26xxx
```

其餘一句話帶過：`local_other` 列名稱標「非 47 集合，不動」；其中 `redmine-skill` 是本 skill
改名前的舊版，可提醒使用者自行移除（`rm -rf ~/.claude/skills/redmine-skill`），不代刪。
`shadows` 每筆列完整路徑，說明同名並存會讓 Claude 載到哪一份不確定；plugin cache 的影子在
plugin 4.0.0 之後會自然消失。

## 給維護者看的幾件事

- **開發保護**：正在本機改某支 47 的 skill 時，在該目錄放一個空檔 `.nineder-dev`，`sync.sh`
  就完全不碰它（報告標「開發中」）。改完、上傳、票頭推到新版後把標記拿掉，下次同步會裝回
  Redmine 版。沒有這個標記，本機領先的版本會被標「本機領先」但**不會被降級覆寫**。
- **下架去哪了**：47 的票不再是 Resolved 時，本機目錄搬到 `~/.claude/nineder/disabled/名稱.disabled-日期`，
  不刪。不留在 `~/.claude/skills/` 底下改名，是因為留在那裡 Claude Code 會把它當成另一支 skill 載入。
- **自我更新**：本 skill 自己也是 47 的一張票（#26915）。升版後下次開對話 `sync.sh` 會連自己
  一起換掉；整支邏輯包在 `main()` 裡，bash 先讀完再執行，刪掉自己所在目錄不影響那一次執行。
- **不自我下架**（v1.1 修正其訊息措辭：它是「已安裝、刻意保留」，不是「未安裝」）：#26915 若不是 Resolved（例如還在等核可、或被退回 In Progress），本機已裝的
  `nineder-skill` **保留不搬**，只在報告列一行。把同步器自己搬走會讓這台機器失去同步能力，
  要等 plugin 的 bootstrap 重種 seed 版才回得來——那可能比現裝的還舊。
- **要開放第二個自動安裝專案**：改 `sync.sh` 頂端 `AUTO_PROJECT_IDS`，並同步改 #26915 與 #26309。
- **cron 入口**：`sync.sh --sync` 與 `--auto` 相同，預設不排，使用者要自己 opt-in。

## 退場條件

| 情況 | 改用什麼 |
| --- | --- |
| 要產出新 Skill 或替既有 Skill 升版 | `/redmine-skill-create`（ "#26921":https://redmine.nineder.com/issues/26921 ） |
| 只要換綁 Google 帳號 | `/nineder-google-login`（ "#26935":https://redmine.nineder.com/issues/26935 ） |
| 要查、建、改 Redmine 議題 | `/redmine` |
| 要管理 plugin 本身（安裝、更新、移除） | Claude Code 的 plugin 機制；plugin 現在只剩 bootstrap |
| 該 skill 只對一個人、一台機器成立 | 放個人目錄，不進 47；本 skill 不會動它 |
