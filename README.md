# nineder Claude Plugin marketplace

耐德科技的 Claude Plugin marketplace。**一個 repo，每個 plugin 一個子目錄。**

## 結構

```
nineder/claude/plugin                  （本 repo）
├── .claude-plugin/marketplace.json    marketplace 定義，列出所有 plugin
├── redmine/                           Redmine 技能組
│   └── .claude-plugin/plugin.json
└── google/                            Google Workspace 技能組
    └── .claude-plugin/plugin.json
```

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
2. 目錄內放 `.claude-plugin/plugin.json`（含 `name`、`version`）與 `skills/`、`commands/` 等
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

規範與沿革記錄在 Redmine，詳見本 repo 的 marketplace 說明議題。
