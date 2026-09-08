#!/usr/bin/env bash
# UserPromptSubmit hook: scans the user's message for two kinds of company
# references and, when any are found, injects a context note (stdout on exit
# code 0 is added to context):
#   1. Redmine issue refs (#NNNN or redmine.nineder.com/issues/NNNN, 4-6
#      digits) -> number->URL table so replies always render the numbers as
#      links (writing guideline #26311 rule 16). Rule 21 renaming is injected
#      ONLY on a session's first prompt; on every later prompt the note tells
#      Claude explicitly NOT to rename (rule 21 as of guideline v7.15).
#      Spec: https://redmine.nineder.com/issues/26559 (v2.3)
#   2. GitLab repo short paths (namespace/repo, leading slash optional) whose
#      first segment matches the company's top-level namespace allowlist ->
#      path->URL candidates. The note tells Claude to link them only after
#      confirming from context that the string really refers to a company repo
#      (rule 19) — better to miss a link than to fabricate one.
#      Spec: https://redmine.nineder.com/issues/26851
# Repo existence is deliberately NOT verified (needs credentials + network on
# every prompt); no browser is ever opened.
# Default-on; set REDMINE_ISSUE_CONTEXT=0 to disable both scans without
# waiting for a new plugin release. Fail-open: every path exits 0 and stays
# silent so the user's message is never blocked.
set -uo pipefail

BASE="https://redmine.nineder.com/issues"
GITLAB="https://gitlab.nineder.com"

# Top-level GitLab namespaces (groups + user namespaces), space-delimited with
# a leading and trailing space for exact-word matching. Snapshot 2026-08-31;
# regenerate per #26851 (GitLab API /namespaces) when publishing a new version.
NAMESPACES=" GitLab-Admin-Bot GitLabDatadog GitLabDuo HoganSu Jenkins ad-team addisonchang ai-automation ai-dashboard alert-bot alexchiu arespeng aso beginner-project billliu charleslu cicd claude_code_skills clawuser delight directus enterprise ghost group-buy-auto groupbuy99 heath-check howardchou hr idd-shared instantaneous108 investigator itintern jacob.chang kingnet_developoer kwchou logistic99 netsuite_members nineder ninederxmomagic optimize99 pondinchen project_122_bot project_123_bot_51f41819c263d3d69511b76d1ab6fbbe project_87_bot root roselo sandyhong select99 sherrywang sid-mis sid-shipping sid-system support-bot techengwang test-idd tinahuang tinawu util watsonlin wesleyweng wtc.justin82 yuchiluo "

[ "${REDMINE_ISSUE_CONTEXT:-1}" != "0" ] || exit 0

input=$(cat 2>/dev/null) || exit 0
[ -n "$input" ] || exit 0

prompt=""
transcript=""
if command -v jq >/dev/null 2>&1; then
  prompt=$(printf '%s' "$input" | jq -r '.prompt // ""' 2>/dev/null) || prompt=""
  transcript=$(printf '%s' "$input" | jq -r '.transcript_path // ""' 2>/dev/null) || transcript=""
elif command -v python3 >/dev/null 2>&1; then
  prompt=$(printf '%s' "$input" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("prompt",""))' \
    2>/dev/null) || prompt=""
  transcript=$(printf '%s' "$input" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("transcript_path",""))' \
    2>/dev/null) || transcript=""
fi
[ -n "$prompt" ] || exit 0

# First prompt of a brand-new session: the transcript file does not exist yet,
# or holds no assistant message. Resumed sessions already have assistant lines
# so they are never misjudged as new. If transcript_path is missing or
# unreadable we treat it as NOT the first turn, i.e. we tell Claude not to
# rename — the conservative side now that mid-conversation renaming is banned
# outright (never misjudge into an unwanted rename, never block) — #26559 v2.3.
first_turn=0
if [ -n "$transcript" ]; then
  if [ ! -f "$transcript" ]; then
    first_turn=1
  elif ! grep -m1 -q '"type":"assistant"' "$transcript" 2>/dev/null; then
    first_turn=1
  fi
fi

ids=$(printf '%s' "$prompt" \
  | grep -oE '#[0-9]+|redmine\.nineder\.com/issues/[0-9]+' \
  | grep -oE '[0-9]+' \
  | awk 'length($0) >= 4 && length($0) <= 6 && !seen[$0]++') || ids=""

# Repo candidates: slash-joined tokens whose first segment is a known
# namespace. Greedy token match keeps filesystem paths like /Users/delight/x
# out (first segment "Users" is not a namespace). Tokens whose last segment
# looks like a source/asset file are skipped — repos rarely end in .js/.md/…
FILE_EXTS=" js ts jsx tsx py rb go java c h cpp cs css scss html htm md json yml yaml toml ini conf sh bash zsh txt log csv png jpg jpeg gif svg ico pdf lock xml sql erb vue php swift kt gradle env "
repos=$(printf '%s' "$prompt" \
  | grep -oE '[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+' \
  | sed -E 's/\.git$//; s/\.+$//' \
  | awk -v ns="$NAMESPACES" -v exts="$FILE_EXTS" -F/ '
      index(ns, " " $1 " ") == 0 { next }
      {
        last = tolower($NF)
        dot = 0
        if (index(last, ".") > 0) {
          n = split(last, parts, ".")
          if (index(exts, " " parts[n] " ") > 0) dot = 1
        }
      }
      dot == 1 { next }
      !seen[$0]++') || repos=""

[ -n "$ids" ] || [ -n "$repos" ] || exit 0

if [ -n "$ids" ]; then
  printf '[redmine plugin] 本則訊息提及下列 Redmine 議題：\n'
  for id in $ids; do
    printf -- '- #%s → %s/%s\n' "$id" "$BASE" "$id"
  done
  printf '%s\n' \
    '依 /redmine 基本寫入準則（#26311）：' \
    '1. 第 16 條：回覆中每一次出現上述編號，都必須輸出為對應的 markdown 超連結，不得留裸編號。'
  if [ "$first_turn" = "1" ]; then
    set -- $ids
    printf '2. 第 21 條【強制】：本 session 是全新 session，且首則訊息含議題編號——不論該議題是否為本次任務對象，一律無條件先以 #%s get_issue 取得 subject，呼叫 ccd_session_mgmt 的 set_session_title（session_id 用 self）把 session 改名為「#%s subject」，改名完成後才開始處理任務；環境沒有該工具時靜默跳過，直接繼續任務。\n' "$1" "$1"
  else
    printf '%s\n' \
      '2. 第 21 條【不要改名】：這不是本 session 的首則訊息（或無法判定），一律不得更改 session 名稱——即使這則訊息貼了新的議題編號、或接下來會建立新議題，也不改。session 名稱只由第一則訊息決定。'
  fi
fi

if [ -n "$repos" ]; then
  printf '[redmine plugin] 本則訊息含疑似公司 GitLab repo 短路徑（第一段已命中 namespace 清單）：\n'
  for r in $repos; do
    printf -- '- %s → %s/%s\n' "$r" "$GITLAB" "$r"
  done
  printf '%s\n' \
    '依 /redmine 基本寫入準則（#26311）第 19 條：先依上下文確認該字串確實是在指公司 repo（不是檔案系統路徑、log 內文或巧合的斜線字串）——確認了才把回覆中每一次出現都輸出為上述超連結（連結文字用短路徑）；不確定就不要連，寧可漏連、不可錯連。'
fi
exit 0
