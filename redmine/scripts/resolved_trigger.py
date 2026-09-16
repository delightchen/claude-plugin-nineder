#!/usr/bin/env python3
"""PostToolUse hook（掛在 update_issue 上）：議題被推到 Resolved 時，
背景補跑一次採集器。

Redmine #27090 排程的三個觸發點之一（另兩個是 daily_trigger.py 與手動
執行 collect.py）：議題進入 Resolved 是工作告一段落的時刻，把還沒歸帳
的用量收一次，比等固定時間的排程更貼合實際。

只看 update_issue 的回應有沒有把狀態改成 Resolved——不管這次更新改了
別的什麼欄位。判斷不到就什麼都不做，永遠不擋下這次寫入（fail-open）。
每次呼叫都留一行除錯紀錄（不只在真的觸發時才記），因為 tool_response
的實際外觀一度跟程式假設的不一樣（2026-09-16 抓到並修好：真實回應最外層
是 list，不是包在 dict 裡；已用兩次真實的 update_issue 呼叫重放驗證過，
見 test_resolved_trigger.py），留著這支除錯紀錄是為了往後還能繼續回答
「有沒有抓到」，不是因為還沒驗證過。
"""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

DEBUG_LOG_PATH = os.path.expanduser("~/.claude/nineder/resolved_trigger_log.jsonl")
# 隨 plugin 分發時跟 collect.py 一起複製到 ~/.claude/nineder/bin/（見
# bootstrap.sh 步驟 0），因此抓同目錄下的檔案，不寫死我本機的開發路徑。
COLLECTOR = str(Path(__file__).resolve().parent / "collect.py")


def extract_status(response) -> str | None:
    """從 PostToolUse 的 tool_response 挖出議題的 status 字串。

    外觀可能是已經解開的物件（summarize_issue 的形狀，status 直接是
    字串），也可能是 MCP 的文字信封——後者實機觀察到的是一個 list（例如
    `[{"type": "text", "text": "..."}]`），不是包在 `{"content": [...]}`
    裡的 dict；兩種寫法在 2026-09-15 的兩次真實 update_issue 呼叫（issue
    26969、27062）上都對過，只認 dict 版本會讓 status 永遠抓成 None。
    三種都試，缺什麼都不強求，找不到就回 None。
    """
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return None

    content = None
    if isinstance(response, dict):
        status = response.get("status")
        if isinstance(status, str):
            return status
        content = response.get("content")
    elif isinstance(response, list):
        content = response
    else:
        return None

    if isinstance(content, list):
        for blk in content:
            if not (isinstance(blk, dict) and blk.get("type") == "text"):
                continue
            try:
                parsed = json.loads(blk.get("text", ""))
            except ValueError:
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get("status"), str):
                return parsed["status"]
    return None


def debug_log(record: dict) -> None:
    try:
        os.makedirs(os.path.dirname(DEBUG_LOG_PATH), exist_ok=True)
        with open(DEBUG_LOG_PATH, "a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        debug_log({"ts": _now(), "error": "stdin 不是合法 JSON"})
        return 0

    status = extract_status(event.get("tool_response"))
    launched = False

    if status == "Resolved" and os.path.exists(COLLECTOR):
        try:
            subprocess.Popen(
                [sys.executable, COLLECTOR, "--trigger", "issue_resolved"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
            launched = True
        except Exception:
            pass  # fail-open：這支永遠不該擋下 update_issue 的寫入

    debug_log({"ts": _now(), "status": status, "launched": launched})
    return 0


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open 兜底：這支腳本自己的任何錯都不該讓寫入失敗
