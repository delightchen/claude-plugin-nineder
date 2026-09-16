#!/usr/bin/env python3
"""SessionStart hook：每天第一個 session 啟動時，背景補跑一次採集器。

Redmine #27090 驗收第九組的排程，決定不用固定時間的 cron/launchd，改成
三個事件觸發（這是其中之一，另兩個是 resolved_trigger.py 與手動執行
collect.py）：沒有人在用的時候，對話紀錄本來就不會變，跑了也是白跑；
「第一個 session 開始」與「議題被推到 Resolved」才是真的有新資料值得收
的時刻。

只負責「今天觸發過一次」的判斷——用一個記著日期的標記檔，同一天內的
後續 session 一律跳過，不重複啟動。失敗與否、實際掃到多少，都交給
collect.py 自己的執行紀錄（collector_runs.jsonl），這裡只負責啟動，
永遠不擋下 session 開始（fail-open：任何例外都吞掉，exit 0）。
"""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

MARKER_PATH = os.path.expanduser("~/.claude/nineder/collector_daily_marker")
DEBUG_LOG_PATH = os.path.expanduser("~/.claude/nineder/daily_trigger_log.jsonl")
# 隨 plugin 分發時跟 collect.py 一起複製到 ~/.claude/nineder/bin/（見
# bootstrap.sh 步驟 0），因此抓同目錄下的檔案，不寫死我本機的開發路徑。
COLLECTOR = str(Path(__file__).resolve().parent / "collect.py")


def already_ran_today() -> bool:
    try:
        with open(MARKER_PATH) as fh:
            return fh.read().strip() == datetime.date.today().isoformat()
    except OSError:
        return False


def mark_today() -> None:
    # 先標記再啟動：同一天內近乎同時開好幾個 session 時，最多只有一個
    # 會真的搶到啟動，其餘看到標記就跳過——不用鎖，重複啟動一次也無傷
    # （collect.py 本身是安全的重跑），但沒必要每個 session 都跑一次。
    try:
        os.makedirs(os.path.dirname(MARKER_PATH), exist_ok=True)
        with open(MARKER_PATH, "w") as fh:
            fh.write(datetime.date.today().isoformat())
    except OSError:
        pass


def debug_log(record: dict) -> None:
    try:
        os.makedirs(os.path.dirname(DEBUG_LOG_PATH), exist_ok=True)
        with open(DEBUG_LOG_PATH, "a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        sys.stdin.read()  # SessionStart 事件本身用不到，讀掉避免管線卡住
    except Exception:
        pass

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    already = already_ran_today()
    launched = False

    if not already and os.path.exists(COLLECTOR):
        mark_today()
        try:
            subprocess.Popen(
                [sys.executable, COLLECTOR, "--trigger", "session_start"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
            launched = True
        except Exception:
            pass  # fail-open：這支永遠不該擋下 session 開始

    debug_log({"ts": ts, "already_ran_today": already, "launched": launched})
    return 0


if __name__ == "__main__":
    sys.exit(main())
