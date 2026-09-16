#!/usr/bin/env bash
# redmine plugin 4.1.0 —— SessionStart bootstrap 的 POSIX 轉接殼
#
# 4.1.0 起，實際邏輯全部搬進同目錄的 bootstrap.py（純 Python，不含任何殼層語法，
# 理論上 Windows／macOS／Linux 通用）。這支 .sh 現在只做一件事：找到 bootstrap.py
# 並用 python3 執行它，讓既有的呼叫入口（settings.json 裡寫的路徑、/redmine:setup
# 指令的搜尋邏輯）維持不變，不需要跟著這次重構一起改。
#
# 原生 Windows 沒有 bash，這支 .sh 在那邊本來就不會被執行——原生 Windows 上要嘛透過
# WSL／Git-Bash 跑這支殼，要嘛直接找到旁邊的 bootstrap.py 用 python 執行；後者
# 目前還沒有一支對應的 .bat／.ps1 轉接殼，是已知、尚待驗證是否需要的缺口。
#
# 規格正本：Redmine #26559（v3.3）；分發模型：#26309【分發模型 v2】；同步器：#26915；
# 自動夾帳：#27113；用量排程（daily_trigger／resolved_trigger）：#27090；
# Python 化＋初步 Windows 排程支援（未經真實機器驗證）：#27127 附近討論
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  exit 0  # fail-open：找不到 python3 就什麼都不做，不阻擋 session 開始
fi

exec python3 "${SCRIPT_DIR}/bootstrap.py"
