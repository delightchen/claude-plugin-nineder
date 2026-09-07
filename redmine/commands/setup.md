---
description: 完成這台機器的耐德 Claude 環境設定——執行一次啟動設定（寫入 hook、種下同步器、同步公司 Skill），然後接手機器健檢
---

執行這台機器的一次性啟動設定。依序做兩件事，不要跳過第一件：

## 一、執行 bootstrap

用 Bash 執行下面這一行（這只是寫使用者自己家目錄底下的設定，不必先問使用者）：

```bash
bash ~/.claude/plugins/marketplaces/nineder/redmine/scripts/bootstrap.sh
```

它會做四件事，全部冪等：把 `/nineder-skill` 同步器種進 `~/.claude/skills/`（已存在就不碰）、
把兩條 hook 條目寫進 `~/.claude/settings.json`（UserPromptSubmit 與 SessionStart——這是純桌面版
機器唯一跑得到 bootstrap 的路徑）、移除 v3.x 留下的舊指標檔、跑一次 Skill 同步。

**把它印出的每一行逐字轉述給使用者。** 什麼都沒印也要說明：那代表這台機器已經設好了，不是失敗。

腳本找不到（路徑不存在）的話，代表 plugin 沒裝好或版本太舊，請使用者先跑
`claude plugin marketplace update nineder` 與 `claude plugin update redmine@nineder`，
然後**整個重啟** Claude Code 再回來。

## 二、接手機器健檢

bootstrap 跑完後，用 Skill tool 呼叫 `nineder-skill`，由它接著跑「機器健檢七格」：
Redmine API key 鑰匙檔、兩個 MCP 的註冊與登入、Skill 同步、Google 帳號綁定。

`nineder-skill` 是這一次剛被種下去的，**同一個 session 內可能還載入不到**。呼叫不到時不要硬試，
直接告訴使用者：「啟動設定已完成，請**新開一個對話**輸入 `/nineder-skill` 完成剩下的設定」，
並附上手冊連結 https://redmine.nineder.com/projects/website_managfc/wiki/Claude_Code_%E6%96%B0%E6%A9%9F%E5%99%A8%E5%AE%89%E8%A3%9D

## 邊界

- 不要代替使用者貼任何 API key，也不要讀出鑰匙檔的內容——那些由 `nineder-skill` 引導使用者自己做
- 不要自己寫 `rm -rf`、不要自己改 `~/.claude/settings.json`；一切交給 bootstrap.sh
- 執行期間對使用者說的每一句話都用繁體中文

$ARGUMENTS
