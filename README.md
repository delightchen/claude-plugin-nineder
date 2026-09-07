# nineder Claude Plugin marketplace

耐德科技的 Claude Plugin marketplace。**一個 repo，每個 plugin 一個子目錄。**

## 結構

```
nineder/claude/plugin                  （本 repo）
├── .claude-plugin/marketplace.json    marketplace 定義，列出所有 plugin
└── redmine/                           唯一的 plugin，分發模型 v2 起只剩 bootstrap
    ├── .claude-plugin/plugin.json
    ├── hooks/hooks.json               只宣告 SessionStart
    ├── scripts/bootstrap.sh           種同步器、維護 settings hook、觸發同步
    ├── scripts/issue_context.sh       UserPromptSubmit hook
    └── seed/nineder-skill/            同步器種子（不放在 skills/，避免被當 skill 載入）
```

**公司 Skill 的內容不在這個 repo。** 分發模型 v2（2026-09-05，
[#26309](https://redmine.nineder.com/issues/26309)）起，skill 的正本是 Redmine Skill 票的
附檔，成員機器上由 `/nineder-skill`（[#26915](https://redmine.nineder.com/issues/26915)）
同步到 `~/.claude/skills/`。要改 skill 內容就改那張票的附檔，**不必動本 repo、不必發 plugin
版、成員不必重啟**。本 repo 只在改 bootstrap、hook 或 seed 時才需要發版。

google plugin 已於 2026-09-06 整支廢除，其兩支 skill 改由 Skill 票
[#26934](https://redmine.nineder.com/issues/26934)、[#26935](https://redmine.nineder.com/issues/26935)
承載。

## 發佈鏈路

```
gitlab.nineder.com/nineder/claude/plugin
        │  push mirror（GitLab 專案設定 → Repository → Mirroring repositories）
        ▼
github.com/delightchen/claude-plugin-nineder
        │  claude.ai 組織設定 → Plugins 讀取這個 repo
        ▼
組織成員（目前設為 Installed by default）
```

GitLab 是唯一的寫入來源，GitHub 只是鏡像。**不要直接改 GitHub**，會在下次鏡像時被覆蓋。

claude.ai 需要能公開讀取的來源，而公司的 GitLab 是內網私有的，所以中間必須有 GitHub 這一層。

## 新增一個 plugin

不需要開新 repo，也不需要在 claude.ai 加新的 marketplace：

1. 在本 repo 建一個子目錄，例如 `vmware/`
2. 目錄內放 `.claude-plugin/plugin.json`（含 `name`、`version`）與 `hooks/`、`scripts/` 等。
   **新 plugin 不要放 `skills/`** —— skill 走 Redmine Skill 票附檔，理由見上方結構段
3. 在 `.claude-plugin/marketplace.json` 的 `plugins` 陣列加一筆：

```json
{ "name": "vmware", "source": "./vmware", "description": "…", "category": "…" }
```

4. 開 MR 合進 `main`（`main` 是保護分支）
5. 觸發或等待 push mirror
6. 到 claude.ai 組織設定按 **Re-sync**

## 改動既有 plugin 時務必推版本號

`plugin.json` 的 `version` 沒有往上推的話，**自動更新會跳過那一版**，同事拿不到新內容。

## 相關議題

| 議題 | 內容 |
| --- | --- |
| [#26825](https://redmine.nineder.com/issues/26825) | plugin 發佈規範（結構、鏡像、常見錯誤）——本文的正本 |
| [#26309](https://redmine.nineder.com/issues/26309) | 開發準則與【分發模型 v2】 |
| [#26915](https://redmine.nineder.com/issues/26915) | `/nineder-skill` 同步器 |
| [#26937](https://redmine.nineder.com/issues/26937) | 分發模型 v2 的切換記錄 |
