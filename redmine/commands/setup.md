---
description: 完成這台機器的耐德 Claude 環境設定——執行一次啟動設定（寫入 hook、種下同步器、同步公司 Skill），然後接手機器健檢
---

執行這台機器的一次性啟動設定。依序做兩件事，不要跳過第一件：

## 一、執行 bootstrap

用 Bash 執行下面這一段（這只是寫使用者自己家目錄底下的設定，不必先問使用者）：

```bash
BS=""
for c in "${CLAUDE_PLUGIN_ROOT:-/nonexistent}/scripts/bootstrap.sh" \
         "$HOME/.claude/plugins/marketplaces/nineder/redmine/scripts/bootstrap.sh"; do
  [ -f "$c" ] && { BS="$c"; break; }
done
if [ -z "$BS" ]; then
  for c in "$HOME/Library/Application Support/Claude/local-agent-mode-sessions"/*/*/rpm/plugin_*/scripts/bootstrap.sh; do
    [ -f "$c" ] && [ -d "${c%/scripts/bootstrap.sh}/seed/nineder-skill" ] || continue
    [ -z "$BS" ] || [ "$c" -nt "$BS" ] && BS="$c"
  done
fi
[ -n "$BS" ] || [ ! -f "$HOME/.claude/nineder/bin/bootstrap.sh" ] || BS="$HOME/.claude/nineder/bin/bootstrap.sh"
if [ -n "$BS" ]; then echo "bootstrap: $BS"; bash "$BS"; else echo "NOT_FOUND"; fi
```

**為什麼要搜尋而不是寫死一條路徑**（[#26915](https://redmine.nineder.com/issues/26915) note-27）：
plugin 有兩條派發來源，落地位置完全不同——CLI marketplace 在
`~/.claude/plugins/marketplaces/`，而組織派發在
`~/Library/Application Support/Claude/local-agent-mode-sessions/<session-id>/…/plugin_<id>/`，
**後者含 session id、每次開對話都會變**。上面的搜尋順序是：本次 session 的 plugin 目錄 →
CLI marketplace → 組織派發（以 `seed/nineder-skill` 認出是哪一個 plugin，取最新的）→
最後才退回 `~/.claude/nineder/bin/` 的穩定副本。

bootstrap 會做五件事，全部冪等：把自己與 `issue_context.sh` 複製到
`~/.claude/nineder/bin/`（settings 的 hook 一律指向這裡，路徑才穩定）、把 `/nineder-skill`
同步器種進 `~/.claude/skills/`（已存在就不碰）、把兩條 hook 條目寫進
`~/.claude/settings.json`（UserPromptSubmit 與 SessionStart——這是純桌面版機器唯一跑得到
bootstrap 的路徑）、移除 v3.x 留下的舊指標檔、跑一次 Skill 同步。

**把它印出的每一行逐字轉述給使用者。** 什麼都沒印也要說明：那代表這台機器已經設好了，不是失敗。

印出 `NOT_FOUND` 的話，代表這台機器上找不到任何一份 plugin 檔案。請使用者**整個結束
Claude Code 再打開**（不是只關視窗）後重跑一次 `/redmine:setup`；仍然找不到就請他聯絡系統整合部
陳昶任 delight。**不要叫使用者去跑 `claude plugin marketplace add` 或 `install`**——組織派發的
成員沒有那個 repo 的讀取權，那條路會失敗（手冊最後一節有說明）。

## 二、接手機器健檢

bootstrap 跑完後，用 Skill tool 呼叫 `nineder-skill`，由它接著跑「機器健檢七格」：
Redmine API key 鑰匙檔、兩個 MCP 的註冊與登入、Skill 同步、Google 帳號綁定。

`nineder-skill` 是這一次剛被種下去的，**同一個 session 內可能還載入不到**。呼叫不到時不要硬試，
直接告訴使用者：「啟動設定已完成，請**新開一個對話**輸入 `/nineder-skill` 完成剩下的設定」，
並附上手冊連結 https://redmine.nineder.com/projects/47/wiki/Claude_Code_%E6%96%B0%E6%A9%9F%E5%99%A8%E5%AE%89%E8%A3%9D

## 邊界

- 不要代替使用者貼任何 API key，也不要讀出鑰匙檔的內容——那些由 `nineder-skill` 引導使用者自己做
- 不要自己寫 `rm -rf`、不要自己改 `~/.claude/settings.json`；一切交給 bootstrap.sh
- 執行期間對使用者說的每一句話都用繁體中文

$ARGUMENTS
