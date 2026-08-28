# google — 耐德科技 Claude Plugin

`/nineder_google` — 用**你本人的 nineder.com 帳號**讀取並**修改**公司的 Google
Docs、Sheets、Slides。

規格議題：[#26714](https://redmine.nineder.com/issues/26714)

## 安裝

已經裝過 `nineder` marketplace 的人（就是現在在用 `/redmine` 的那些）直接：

```bash
claude plugin install google@nineder
```

接著設定 MCP 連線並登入：

```bash
claude mcp add --scope user --transport http nineder-google https://mcp.nineder.com/google/mcp
claude mcp login nineder-google
```

`claude mcp login` 的同意頁會要你貼上自己的
[Redmine API access key](https://redmine.nineder.com/my/account)。設定完成後**要重啟
Claude Code**，工具 schema 是連線建立當時取得的。

第一次使用時輸入 `/nineder_google`，skill 會偵測到還沒連結 Google 帳號並引導完成。

## 使用資格

要同時滿足兩個條件：

1. **有 Redmine 帳號並能取得 API access key** —— 同意頁會當場向 Redmine 驗證
2. **有 nineder.com 網域的 Google 帳號** —— 同意畫面為 Internal，其他網域被 Google 擋下

## 跟 Claude 內建 Google 連接器的差別

| | 內建連接器 | 本 plugin |
| --- | --- | --- |
| 走誰的 OAuth | Anthropic 自己的 | **公司自有**，可稽核可撤銷 |
| 讀取、建立檔案 | 可以 | 可以 |
| **修改既有文件內文** | **做不到** | **可以** |
| 公司能否控管 | 不能 | 能（Workspace 應用程式存取控制） |

## 服務端

程式碼在 [nineder/mcp](https://gitlab.nineder.com/nineder/mcp) 的
`services/google-python`，部署在 gateway 主機 `mcp-gateway-nineder-vm`。
