#!/usr/bin/env python3
"""session_link_inline.py 的行為驗證（Redmine #27754）。用法：python3 redmine/tests/verify_session_link_inline.py

全部用暫時的 HOME 與假的 App 中繼檔目錄，不碰真實的 ~/.claude 與 App 資料；不需要網路。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "session_link_inline.py")
H = tempfile.mkdtemp()
T = tempfile.mkdtemp()
os.makedirs(os.path.join(T, "a", "b"))


def session(local, cli, bridges=None):
    d = {"sessionId": local, "cliSessionId": cli}
    if bridges is not None:
        d["bridgeSessionIds"] = bridges
    with open(os.path.join(T, "a", "b", local + ".json"), "w") as fh:
        json.dump(d, fh)


session("local_aaaa-bbbb", "cli-none", [])
session("local_cccc", "cli-nofield")
session("local_dddd", "cli-multi", ["session_old000000000000000000AA", "session_new000000000000000000BB"])
session("local_eeee", "cli-one", ["session_01BsEjSMwL7P7P5H5cLE8Eqq"])


def run(event, sessions=T, raw=None):
    env = dict(os.environ, HOME=H, NINEDER_APP_SESSIONS_DIR=sessions)
    p = subprocess.run([sys.executable, SCRIPT], input=raw if raw is not None else json.dumps(event),
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout.strip()


def ev(note, sid):
    return {"tool_name": "mcp__nineder-redmine__create_issue_reminder", "session_id": sid,
            "tool_input": {"issue_id": 1, "note": note, "channels": "telegram"}}


ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print("PASS" if cond else "FAIL", name)


def note_of(out):
    return json.loads(out)["hookSpecificOutput"]["updatedInput"]["note"]


rc, out = run(ev("內容", "cli-one"))
check("有遠端編號：/s/<local_>?r=<session_>（電腦看路徑、手機看 r）", rc == 0 and note_of(out) == "內容\n\n↩︎ 回到這個 session\nhttps://mcp.nineder.com/s/local_eeee?r=session_01BsEjSMwL7P7P5H5cLE8Eqq")
check("其他參數原封不動", json.loads(out)["hookSpecificOutput"]["updatedInput"]["channels"] == "telegram")
check("結尾多餘換行不會疊空行", note_of(run(ev("內容\n\n\n", "cli-one"))[1]).startswith("內容\n\n↩︎"))
check("沒開遠端控制：不帶 r，加請在電腦上點",
      note_of(run(ev("x", "cli-none"))[1]).endswith("（請在電腦上點）\nhttps://mcp.nineder.com/s/local_aaaa-bbbb"))
check("沒有 bridgeSessionIds 欄位也行", "local_cccc" in run(ev("x", "cli-nofield"))[1] and "?r=" not in run(ev("x", "cli-nofield"))[1])
check("路徑絕不放 session_ 編號（桌面 continue 只收 local_）", "/s/session_" not in run(ev("x", "cli-one"))[1])
out = run(ev("x", "cli-multi"))[1]
check("多個遠端編號取最後一個，路徑仍是 local_", "local_dddd?r=session_new000000000000000000BB" in out and "session_old" not in out)

for name, note in [("已有本服務連結", "看 https://mcp.nineder.com/s/local_x"),
                   ("已有舊 Worker 連結", "https://claude-session-link.nineder.workers.dev/s/abc"),
                   ("note 空白", "   ")]:
    rc, out = run(ev(note, "cli-one"))
    check(name + "：不動", rc == 0 and out == "")
rc, out = run({"session_id": "cli-one", "tool_input": {"issue_id": 1}})
check("note 缺：不動", rc == 0 and out == "")
rc, out = run(ev("x", "no-such-session"))
check("找不到 session：不動", rc == 0 and out == "")
rc, out = run({"tool_input": {"note": "x"}})
check("event 沒 session_id：不動", rc == 0 and out == "")
rc, out = run(None, raw="not json")
check("壞 stdin：不動且不報錯", rc == 0 and out == "")
rc, out = run(ev("x", "cli-one"), "/nonexistent")
check("目錄不存在：不動", rc == 0 and out == "")

log = open(os.path.join(H, ".claude", "nineder", "session_link_inline_skip.log")).read()
import re
check("日誌只記原因、不含任何 session 編號（原因名稱本身含 session 字樣不算）",
      not re.search(r"session_[A-Za-z0-9]{20,}|local_[A-Za-z0-9-]+|cli-(one|none|multi|nofield)", log))

shutil.rmtree(H)
shutil.rmtree(T)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
