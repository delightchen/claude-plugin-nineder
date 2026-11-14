#!/usr/bin/env python3
"""GitLab main -> GitHub 鏡像對帳與補推（Redmine #27127）。

比對本 repo 目前 commit 與 GitHub 上目標分支的 SHA；GitHub 落後就以「不帶 force」的方式快轉補推，
推完再驗證一次。失敗（分歧、GitHub 領先、認證失敗、重試用盡）一律結束碼 1，並把失敗寫成 Redmine
留言貼在「當初發動這次發版的議題」上。

環境變數：
  GH_MIRROR_TOKEN   GitHub 寫入憑證（只有補推需要；讀 SHA 不需要）
  REDMINE_API_KEY   貼失敗留言用；沒設就只印出、不貼
  GH_REPO           預設 delightchen/claude-plugin-nineder
  TARGET_REF        預設 refs/heads/main
  REDMINE_URL       預設 https://redmine.nineder.com
  FALLBACK_ISSUE    找不到發動議題時貼在哪張，預設 27127

用法：python3 scripts/mirror_sync.py [--dry-run] [--sha <sha>] [--attribute-only <sha>]
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

GH_REPO = os.environ.get("GH_REPO", "delightchen/claude-plugin-nineder")
TARGET_REF = os.environ.get("TARGET_REF", "refs/heads/main")
REDMINE_URL = os.environ.get("REDMINE_URL", "https://redmine.nineder.com").rstrip("/")
FALLBACK_ISSUE = os.environ.get("FALLBACK_ISSUE", "27127")
GH_URL = f"https://github.com/{GH_REPO}.git"
RETRY_WAITS = (5, 15, 45)


def run(args, check=True):
    return subprocess.run(args, capture_output=True, text=True, check=check)


def scrub(text):
    """輸出前遮掉憑證，避免進 CI 日誌或 Redmine 留言。"""
    for name in ("GH_MIRROR_TOKEN", "REDMINE_API_KEY"):
        val = os.environ.get(name)
        if val:
            text = text.replace(val, "***")
    return text


def gh_head():
    """GitHub 目標分支目前的 SHA；沒有該分支回 None。公開 repo 不需要憑證。"""
    p = run(["git", "ls-remote", GH_URL, TARGET_REF], check=False)
    if p.returncode != 0:
        raise RuntimeError("ls-remote 失敗：" + scrub(p.stderr.strip()))
    line = p.stdout.strip().split("\n")[0]
    return line.split()[0] if line else None


def push(sha):
    token = os.environ.get("GH_MIRROR_TOKEN")
    if not token:
        raise RuntimeError("沒有 GH_MIRROR_TOKEN，無法補推")
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    p = run(["git", "-c", f"http.extraheader=Authorization: Basic {basic}",
             "push", GH_URL, f"{sha}:{TARGET_REF}"], check=False)
    return p.returncode, scrub(p.stderr.strip())


def attribute(sha):
    """找出發動這次發版的議題編號；回 (議題, 依據)。

    順序：分支名稱開頭的編號 -> 「來源 commit：... (#N)」-> 合併內容裡第一個 #N -> 備援議題。
    """
    parents = run(["git", "rev-list", "--parents", "-n", "1", sha]).stdout.split()[1:]
    subject = run(["git", "log", "-1", "--format=%s", sha]).stdout.strip()
    if len(parents) >= 2:
        body = run(["git", "log", f"{parents[0]}..{parents[1]}", "--format=%B"]).stdout
    else:
        body = run(["git", "log", "-1", "--format=%B", sha]).stdout
    m = re.search(r"Merge branch '(?:feature|fix|release)/(\d{4,6})-", subject)
    if m:
        return m.group(1), "分支名稱"
    m = re.search(r"來源 commit：.*\(#(\d{4,6})\)", body)
    if m:
        return m.group(1), "來源 commit"
    m = re.search(r"#(\d{4,6})", body)
    if m:
        return m.group(1), "commit 訊息"
    return FALLBACK_ISSUE, "備援（找不到發動議題）"


def redmine(path, payload=None, method="GET"):
    key = os.environ.get("REDMINE_API_KEY")
    req = urllib.request.Request(
        f"{REDMINE_URL}{path}", method=method,
        data=json.dumps(payload).encode() if payload else None,
        headers={"X-Redmine-API-Key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        return json.loads(body) if body else {}


def report_failure(issue, basis, gl_sha, gh_sha, reason, dry_run):
    marker = f"mirror-sync:{gl_sha[:10]}:{(gh_sha or 'none')[:10]}"
    note = (
        "*GitHub 鏡像補推失敗*\n\n"
        f"|_. 項目 |_. 內容 |\n| GitLab SHA | {gl_sha} |\n| GitHub SHA | {gh_sha or '（分支不存在）'} |\n"
        f"| 目標 | {GH_REPO} {TARGET_REF} |\n| 原因 | {reason} |\n"
        f"| 歸屬依據 | {basis} |\n\n"
        "p. 成員在這個狀態下拿到的仍是舊版。處理方式見 #26825 第五段；排除後重跑該 pipeline 即可。\n\n"
        f"p. {marker}")
    print(note)
    if dry_run or not os.environ.get("REDMINE_API_KEY"):
        print("（dry-run 或沒有 REDMINE_API_KEY：不貼留言）")
        return
    issue_data = redmine(f"/issues/{issue}.json?include=journals")["issue"]
    recent = [j.get("notes") or "" for j in issue_data.get("journals", [])[-20:]]
    if any(marker in n for n in recent):
        print("相同失敗已貼過，略過以免洗版")
        return
    redmine(f"/issues/{issue}.json", {"issue": {"notes": note}}, method="PUT")
    print(f"已貼到 #{issue}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sha")
    ap.add_argument("--attribute-only")
    a = ap.parse_args()
    if a.attribute_only:
        print(*attribute(run(["git", "rev-parse", "--verify", f"{a.attribute_only}^{{commit}}"]).stdout.strip()))
        return 0
    ref = a.sha or os.environ.get("CI_COMMIT_SHA") or "HEAD"
    gl_sha = run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"]).stdout.strip()  # 一律轉成完整 SHA 才能和 GitHub 比對
    issue, basis = attribute(gl_sha)
    print(f"GitLab {gl_sha[:10]}  目標 {GH_REPO} {TARGET_REF}  歸屬 #{issue}（{basis}）")
    try:
        gh = gh_head()
        print(f"GitHub {(gh or 'none')[:10]}")
        if gh == gl_sha:
            print("兩邊一致，無事可做")
            return 0
        if a.dry_run:
            print("dry-run：兩邊不一致，會執行補推")
            return 0
        reason = ""
        for i, wait in enumerate((0,) + RETRY_WAITS):
            time.sleep(wait)
            rc, err = push(gl_sha)
            if rc == 0:
                break
            reason = err.splitlines()[-1] if err else f"git push 結束碼 {rc}"
            print(f"第 {i + 1} 次補推失敗：{reason}")
            if "non-fast-forward" in err or "rejected" in err or "Authentication" in err or "403" in err or "401" in err:
                break  # 重試不會改變結果
        else:
            raise RuntimeError("重試用盡：" + reason)
        if rc != 0:
            raise RuntimeError(reason)
        after = gh_head()
        if after != gl_sha:
            raise RuntimeError(f"補推後驗證不一致（GitHub 現在是 {(after or 'none')[:10]}）")
        print("補推完成並驗證一致")
        return 0
    except Exception as e:  # noqa: BLE001 — 任何失敗都要通知
        report_failure(issue, basis, gl_sha, locals().get("gh"), scrub(str(e)), a.dry_run)
        return 1


if __name__ == "__main__":
    sys.exit(main())
