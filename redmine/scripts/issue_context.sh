#!/usr/bin/env bash
# UserPromptSubmit hook: scans the user's message for Redmine issue references
# (#NNNN or redmine.nineder.com/issues/NNNN, 4-6 digits) and, when any are
# found, injects a context note (stdout on exit code 0 is added to context):
#   1. a number -> URL table so replies always render the numbers as links
#      (writing guideline #26311 rule 16), and
#   2. a reminder to rename the session per rule 21 (get_issue subject +
#      set_session_title; skip silently where the tool does not exist).
# Spec: https://redmine.nineder.com/issues/26559 (v2). No browser is opened —
# the auto-open path was rejected and stays out of scope.
# Default-on; set REDMINE_ISSUE_CONTEXT=0 to disable without waiting for a new
# plugin release. Fail-open: every path exits 0 and stays silent so the user's
# message is never blocked.
set -uo pipefail

BASE="https://redmine.nineder.com/issues"

[ "${REDMINE_ISSUE_CONTEXT:-1}" != "0" ] || exit 0

input=$(cat 2>/dev/null) || exit 0
[ -n "$input" ] || exit 0

prompt=""
if command -v jq >/dev/null 2>&1; then
  prompt=$(printf '%s' "$input" | jq -r '.prompt // ""' 2>/dev/null) || prompt=""
elif command -v python3 >/dev/null 2>&1; then
  prompt=$(printf '%s' "$input" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("prompt",""))' \
    2>/dev/null) || prompt=""
fi
[ -n "$prompt" ] || exit 0

ids=$(printf '%s' "$prompt" \
  | grep -oE '#[0-9]+|redmine\.nineder\.com/issues/[0-9]+' \
  | grep -oE '[0-9]+' \
  | awk 'length($0) >= 4 && length($0) <= 6 && !seen[$0]++') || exit 0
[ -n "$ids" ] || exit 0

printf '[redmine plugin] 本則訊息提及下列 Redmine 議題：\n'
for id in $ids; do
  printf -- '- #%s → %s/%s\n' "$id" "$BASE" "$id"
done
printf '%s\n' \
  '依 /redmine 基本寫入準則（#26311）：' \
  '1. 第 16 條：回覆中每一次出現上述編號，都必須輸出為對應的 markdown 超連結，不得留裸編號。' \
  '2. 第 21 條：若其中的議題就是本次要處理的對象，開始執行前先以 get_issue 取得 subject，並呼叫 ccd_session_mgmt 的 set_session_title（session_id 用 self）把 session 改名為「#編號 subject」；環境沒有該工具時靜默跳過，直接繼續任務。'
exit 0
