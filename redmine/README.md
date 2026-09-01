# Redmine Skill Plugin

耐德科技組織內部的 Claude Plugin：把 `/redmine`（讀寫 Redmine 議題）、`redmine-feature`
（Feature 需求撰寫規範）、`/redmine-feature-create`（互動式建立 Feature 需求單）、
`/redmine-bug`（Bug 撰寫規範／review）、`/redmine-bug-create`（互動式建立 Bug 單）五個
skill 打包成單一 plugin，組織成員安裝一次即可使用，更新隨 plugin 版本發佈。

## 安裝（組織成員）

```bash
claude plugin marketplace add https://gitlab.nineder.com/nineder/claude/plugin/redmine.git
claude plugin install redmine@nineder
```

（repo 是 private——第一次 clone 需要公司 GitLab（gitlab.nineder.com）帳號憑證；機器上要
先設定過 git 對 gitlab.nineder.com 的 HTTPS 認證，或改用 SSH URL。）

### 從舊 host（gitlabnew）遷移

2026-08 GitLab 移機前裝過的機器，marketplace 註冊指向 `gitlabnew.nineder.com` 舊網址——
舊 host 停機後 `claude plugin marketplace update` 會開始失敗。請重新註冊一次（skill 內容、
hotkey、MCP 授權都不受影響，hotkey 由 SessionStart hook 自動重建）：

```bash
claude plugin uninstall redmine@nineder
claude plugin marketplace remove nineder
claude plugin marketplace add https://gitlab.nineder.com/nineder/claude/plugin/redmine.git
claude plugin install redmine@nineder
```

安裝後在 Claude Code 輸入 `/redmine <任務>` 即可使用（首次使用會自動引導完成這台機器的
Redmine MCP 授權設定）。

## 更新

```bash
claude plugin marketplace update nineder
claude plugin update redmine@nineder
```

之後重啟 Claude Code（或執行 `/reload-plugins`）載入新版。

## 結構

- `.claude-plugin/plugin.json` — plugin 資訊清單（**每次發佈都要把 version 往上推**，否則
  客戶端的更新檢查會跳過這一版）
- `.claude-plugin/marketplace.json` — 本 repo 同時是 marketplace（名稱 `nineder`）
- `skills/redmine/` — 主 skill：MCP 連線偵測/設定引導/任務執行/寫入準則；
  `scripts/upload_attachment.sh` 為大檔案附件上傳腳本
- `skills/redmine-feature/` — 被動的 Feature 撰寫規範（review 用，不執行寫入）：需求者提需求
  ＋開發者快速 Note 雙情境，Note 情境強制留 GitLab commit／GCP Machine／重大結論記錄
- `skills/redmine-feature-create/` — 主動的互動式建單流程
- `skills/redmine-bug/` — 被動的 Bug 撰寫規範（回報型/調查型分流，review 用，不執行寫入）
- `skills/redmine-bug-create/` — 主動的互動式 Bug 建單流程
- `commands/` — slash 指令入口（plugin 指令一律帶命名空間：`/redmine:redmine`、
  `/redmine:redmine-feature-create` 等）
- `hooks/hooks.json` ＋ `scripts/install_hotkeys.sh` — SessionStart hook：每次 session 啟動
  由 harness 自動（冪等地）把裸名指標檔寫進 `~/.claude/commands/`，讓成員可以直接打
  `/redmine`、`/redmine-feature-create`、`/redmine-bug`、`/redmine-bug-create`（不用帶前綴）。Claude Code 的 plugin 指令強制帶命名
  空間前綴，這是官方機制下唯一能保證裸名指令的做法；指標檔只有幾行、不含任何 skill 內容，
  跟舊的 heredoc 內容同步機制（模型驅動、易 drift、易被跳過）本質不同
- `scripts/issue_context.sh` — UserPromptSubmit hook（[#26559](https://redmine.nineder.com/issues/26559)、
  [#26851](https://redmine.nineder.com/issues/26851)）：你送出的訊息裡只要出現 Redmine 議題編號
  （`#26311` 或議題網址形式），就自動注入一段 context——每個編號對應的
  `redmine.nineder.com` 連結對照表，加上「回覆中編號一律輸出為超連結」（準則第 16 條）與
  「先把 session 改名為 `#編號 subject`」（第 21 條）兩條提醒；**全新 session 的第一則訊息**
  含編號或議題連結時，改名是無條件強制的（不論是否為任務對象）。訊息裡出現公司 GitLab repo
  短路徑（例如 `/charleslu/slap`，第一段命中內建 namespace 清單）時，同樣注入
  `gitlab.nineder.com` 連結候選，由 Claude 依上下文確認真的是 repo 才輸出連結（第 19 條，
  寧可漏連不可錯連；檔案路徑如 `/Users/...` 不會觸發）。不會開啟任何瀏覽器頁面；預設啟用，
  設環境變數 `REDMINE_ISSUE_CONTEXT=0` 即停用；腳本 fail-open，任何錯誤都不會擋住你的訊息。
  **執行路徑（v3.14.0 起）**：桌面版 App 不執行 plugin 宣告的 UserPromptSubmit hook（已知
  CLI/Desktop parity gap，[anthropics/claude-code#45514](https://github.com/anthropics/claude-code/issues/45514)），
  所以本 hook 改由 `scripts/install_settings_hook.sh`（SessionStart 時冪等執行）把執行條目
  維護進使用者的 `~/.claude/settings.json`——settings 層 hooks 官方文件明寫 CLI 與桌面版都
  適用；plugin 的 hooks.json 刻意**不**宣告 UserPromptSubmit，避免 CLI 環境重複注入。
  解除安裝 plugin 後該條目會靜默 no-op（有腳本存在性防呆），可手動自 settings.json 移除

## 規格治理（單一事實來源）

skill 行為規格維護在 Redmine 議題，**改 skill 之前先改規格議題，再同步這裡的檔案**：

- [#26309](https://redmine.nineder.com/issues/26309) — Plugin 化總議題
- [#26311](https://redmine.nineder.com/issues/26311) — `/redmine` 基本寫入準則
- [#26312](https://redmine.nineder.com/issues/26312) — `redmine-feature` 撰寫規範
- [#26313](https://redmine.nineder.com/issues/26313) — `redmine-feature-create` 互動建立流程
- [#26314](https://redmine.nineder.com/issues/26314) — `redmine-bug` Bug 撰寫規範
- [#26315](https://redmine.nineder.com/issues/26315) — `redmine-bug-create` 互動建立 Bug 單

## 發佈與鏡像

主要開發 remote 是公司 GitLab（本 repo，host `gitlab.nineder.com`）。GitLab 端已設定
**push mirroring** 到 GitHub private repo `delightchen/claude-plugin-redmine`（供
claude.ai Organization Settings 的 GitHub App 派發使用）——**維護者只要讓變更進到
GitLab main，GitHub 鏡像會自動同步**，不需要手動雙推。

`main` 為保護分支（直接 push 被設為 No one，2026-08-26 起）。發佈流程：改檔 →
`plugin.json` version 往上推 → push 到 `release/<版本>` 分支 → 開 MR → merge 進 main
（Maintainer 以上可 merge，可透過 GitLab API 完成整段）。

歷史：本 plugin 取代了舊的「單一 `redmine.skill` 上傳 Organization Settings ＋ 本機
heredoc 同步」機制（[#26137](https://redmine.nineder.com/issues/26137) 鐵律時代，開發記錄
見 [#26233](https://redmine.nineder.com/issues/26233) 及其子議題）。
