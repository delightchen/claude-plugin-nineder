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
"""

import os
import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    target = sys.argv[1]
    try:
        if os.path.exists(target):
            subprocess.call([sys.executable, target])
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
