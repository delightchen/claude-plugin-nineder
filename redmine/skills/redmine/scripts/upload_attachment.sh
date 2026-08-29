#!/usr/bin/env bash
# Uploads a local file straight to Redmine's /uploads.json via curl --data-binary
# (raw bytes read directly off disk, no base64 round-trip through Claude's own
# text generation) and prints {token, id, filename, content_type, filesize} as
# JSON on stdout. Exits non-zero with a clear stderr message on any failure.
set -uo pipefail

FILE_PATH="${1:-}"
FILENAME="${2:-}"

if [[ -z "$FILE_PATH" ]]; then
  echo "usage: upload_attachment.sh <local file path> [filename]" >&2
  exit 2
fi

if [[ ! -r "$FILE_PATH" ]]; then
  echo "file not found or not readable: $FILE_PATH" >&2
  exit 1
fi

if [[ -z "$FILENAME" ]]; then
  FILENAME="$(basename "$FILE_PATH")"
fi

if [[ -z "${REDMINE_API_KEY:-}" ]]; then
  # Non-interactive shells don't source ~/.zshrc automatically.
  # shellcheck disable=SC1090
  source ~/.zshrc >/dev/null 2>&1 || true
fi

if [[ -z "${REDMINE_API_KEY:-}" ]]; then
  echo "REDMINE_API_KEY is not set (checked env and ~/.zshrc)" >&2
  exit 1
fi

BASE_URL="${REDMINE_BASE_URL:-https://redmine.nineder.com}"
ENCODED_FILENAME="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$FILENAME")"

HTTP_RESPONSE="$(curl -s -w '\n%{http_code}' --data-binary "@${FILE_PATH}" \
  -H "Content-Type: application/octet-stream" \
  -H "X-Redmine-API-Key: ${REDMINE_API_KEY}" \
  "${BASE_URL}/uploads.json?filename=${ENCODED_FILENAME}")"

HTTP_STATUS="${HTTP_RESPONSE##*$'\n'}"
RESPONSE_BODY="${HTTP_RESPONSE%$'\n'*}"

if [[ "$HTTP_STATUS" != "201" ]]; then
  echo "upload failed: Redmine returned HTTP $HTTP_STATUS: $RESPONSE_BODY" >&2
  exit 1
fi

python3 - "$RESPONSE_BODY" "$FILENAME" "$FILE_PATH" <<'PY_PARSE_UPLOAD_RESPONSE'
import json, os, sys

response, filename, path = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    upload = json.loads(response)["upload"]
except (json.JSONDecodeError, KeyError):
    print(f"upload failed: unexpected response from Redmine: {response}", file=sys.stderr)
    sys.exit(1)

print(json.dumps({
    "token": upload["token"],
    "id": upload.get("id"),
    "filename": filename,
    "content_type": "application/octet-stream",
    "filesize": os.path.getsize(path),
}))
PY_PARSE_UPLOAD_RESPONSE
