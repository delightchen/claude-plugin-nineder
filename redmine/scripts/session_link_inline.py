#!/usr/bin/env python3
"""建排程提醒之前，自動把「回到這個 session」的連結補進 note。

為什麼要有這支：/redmine v3.26 把「建提醒時 note 附回程連結」寫成 skill 條文（Redmine #26311
第 18 條補充），靠模型照三個步驟自己組連結。那是模型自律：漏了不會有任何錯誤，只是使用者收到
一則回不去的通知。連結需要的兩個編號（桌面 App 的 session 編號、遠端控制編號）都只存在這台
機器的 App 中繼檔裡，Redmine 的 MCP 是遠端的看不到；模型要先呼叫 get_session、再跑一段 python
才拿得到。兩邊都拿不到的東西，只有本機的 hook 讀得到——與 ai_usage_inline.py 同一個道理，
所以同樣把它從「記得做」搬到 PreToolUse hook 上。規格：Redmine #27754（連結服務）、
#26311 第 18 條（skill 條文），本檔隨 plugin 分發。

怎麼找到是哪個 session：hook 的 stdin 帶 session_id，那是 Claude Code 的逐字稿 UUID，
App 中繼檔（claude-code-sessions/**/local_*.json）裡的 cliSessionId 欄位就是它；同一份中繼檔
還有 sessionId（local_ 開頭）與 bridgeSessionIds（遠端控制編號，session_ 開頭）。

四條不可以違反的規則（承 ai_usage_inline.py 前三條）：

1. 編號一律來自 App 中繼檔的逐字內容，不解讀、不猜、不補。
2. 拿不到就不要帶。找不到中繼檔（純終端機、舊版 App、檔案格式變了）、note 是空的、或例外，
   都是安靜地什麼都不做——使用者原本的提醒照常建立。
3. 永遠不要擋下寫入。補連結失敗的代價是這則通知少一條連結。
4. note 裡已經有回程連結（本服務的 mcp.nineder.com/s/，或舊的 Cloudflare Worker 網址，例如
   session-notify skill 已經附了）就不再加第二條。

沒有遠端控制編號時（這個 session 沒開過遠端控制）連結退回 /s/<local_ 編號>，並在標題行註明
「請在電腦上點」——手機點那種連結只會看到提示頁，不註明使用者會以為壞了。

連結服務不存任何資料、不認人（Redmine #27754）；本檔也不把任何編號寫進日誌，只記放棄原因。
"""

import glob
import json
import os
import sys
import time
from pathlib import Path

BASE = "https://mcp.nineder.com/s/"
# note 已經有這些字樣之一就視為已附連結。舊 Worker 網址留著：session-notify skill 切換前還在附它。
ALREADY_HAS = ("mcp.nineder.com/s/", "claude-session-link.nineder.workers.dev/s/")
LABEL = "↩︎ 回到這個 session"
LABEL_DESKTOP_ONLY = "↩︎ 回到這個 session（請在電腦上點）"
SKIP_LOG = os.path.expanduser("~/.claude/nineder/session_link_inline_skip.log")


def log_skip(reason, **extra):
    """記一行「這次為什麼沒有補連結」。盡力而為，失敗就算了；絕不記任何 session 編號。"""
    try:
        os.makedirs(os.path.dirname(SKIP_LOG), exist_ok=True)
        entry = {"at": time.time(), "reason": reason}
        entry.update(extra)
        with open(SKIP_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def nothing(reason, **extra):
    log_skip(reason, **extra)
    sys.exit(0)


def app_sessions_dirs():
    """App 中繼檔可能的根目錄。測試或特殊安裝用 NINEDER_APP_SESSIONS_DIR 覆寫。"""
    override = os.environ.get("NINEDER_APP_SESSIONS_DIR")
    if override:
        return [Path(override)]
    home = Path.home()
    cands = [home / "Library" / "Application Support" / "Claude" / "claude-code-sessions"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        cands.append(Path(appdata) / "Claude" / "claude-code-sessions")
    cands.append(home / ".config" / "Claude" / "claude-code-sessions")
    return cands


def find_app_session(cli_session_id=None, local_id=None):
    """回傳 (sessionId, 遠端控制編號或 None)；找不到回 None。依 cliSessionId 或 local_ 編號查。"""
    for root in app_sessions_dirs():
        if not root.is_dir():
            continue
        pattern = f"**/{local_id}.json" if local_id else "**/local_*.json"
        for fp in glob.glob(str(root / pattern), recursive=True):
            try:
                with open(fp, encoding="utf-8") as fh:
                    d = json.load(fh)
            except Exception:
                continue
            if local_id:
                if d.get("sessionId") != local_id:
                    continue
            elif d.get("cliSessionId") != cli_session_id:
                continue
            sid = d.get("sessionId")
            if not isinstance(sid, str) or not sid.startswith("local_"):
                continue
            bridges = d.get("bridgeSessionIds") or []
            remote = bridges[-1] if bridges and isinstance(bridges[-1], str) else None
            return sid, remote
    return None


def build_block(local_id, remote_id):
    """要接在 note 後面的兩行。有遠端控制編號用單一編號形式，電腦與手機通用；沒有就只能電腦點。"""
    if remote_id:
        return f"{LABEL}\n{BASE}{remote_id}"
    return f"{LABEL_DESKTOP_ONLY}\n{BASE}{local_id}"


def main():
    try:
        event = json.load(sys.stdin)
    except Exception as e:
        nothing("stdin_parse_error", error=str(e))

    tool_input = event.get("tool_input") or {}
    note = tool_input.get("note")
    if not isinstance(note, str) or not note.strip():
        nothing("note_empty")
    if any(s in note for s in ALREADY_HAS):
        nothing("note_already_has_link")

    cli_id = event.get("session_id")
    if not cli_id:
        nothing("no_session_id_in_event")

    found = find_app_session(cli_session_id=cli_id)
    if not found:
        nothing("app_session_not_found")
    local_id, remote_id = found

    new_note = note.rstrip() + "\n\n" + build_block(local_id, remote_id)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": dict(tool_input, note=new_note),
        }
    }, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        # 這支腳本的任何失敗都不該讓使用者的提醒建不起來。
        nothing("unhandled_exception", error=str(e))
