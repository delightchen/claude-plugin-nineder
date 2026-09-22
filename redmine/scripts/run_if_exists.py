#!/usr/bin/env python3
"""python3 run_if_exists.py <目標 .py 路徑> —— 目標存在就用同一顆直譯器執行，
不存在就靜默結束，一律 exit 0。

給 settings.json 的 hook 指令用（4.1.0 新增，見 bootstrap.py 的 build_hooks_want）：
不管目標腳本存不存在，這支永遠不會讓 SessionStart／PreToolUse／PostToolUse 因為
找不到檔案而報錯或印出一堆 traceback——理由跟各觸發腳本自己內部的 fail-open 設計
一致（任何錯誤都不該擋下使用者的操作）。

只用 os.path 與 subprocess，不含任何殼層語法，Windows／macOS／Linux 通用；
唯一的前提是 hook 指令本身用同一顆 Python 直譯器呼叫這支檔案（bootstrap.py 寫
settings.json 時用 sys.executable 保證這點）。

4.1.6：#27248 查出這支轉接殼把目標腳本的例外與非零結束碼整段吞掉、完全不留
痕跡——本檔呼叫的任何腳本（含它們自己內部已經 fail-open 過的失敗）在這一層
再壞一次就徹底查無對證。這版補上 LOG_PATH，只在「目標腳本本身丟出例外」或
「結束碼非 0」這兩種不正常情況記一行，目標不存在（原本就預期的情境）不記；
一樣不改變本檔原有的 fail-open 行為，寫 log 失敗也一樣吞掉。
"""

import json
import os
import subprocess
import sys
import time

LOG_PATH = os.path.expanduser("~/.claude/nineder/run_if_exists_skip.log")


def _log(reason, target, **extra):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        entry = {"at": time.time(), "reason": reason, "target": target}
        entry.update(extra)
        with open(LOG_PATH, "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    target = sys.argv[1]
    try:
        if os.path.exists(target):
            rc = subprocess.call([sys.executable, target])
            if rc != 0:
                _log("target_nonzero_exit", target, returncode=rc)
    except Exception as e:
        _log("launch_exception", target, error=str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
