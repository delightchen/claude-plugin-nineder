#!/usr/bin/env python3
"""寫 Redmine 之前，自動把本輪的 AI 用量補進工具參數。

為什麼要有這支：token 只存在於這台機器的對話紀錄裡。Redmine 的 MCP 是遠端的
（https://mcp.nineder.com/redmine/mcp），它看得到工具參數，看不到 transcript；
模型看不到自己的用量，也不得申報。兩邊都拿不到的東西，只有本機的採集器算得出
來。過去的做法是「寫 note 之前記得先跑 collect.py --pending 再把輸出貼進
ai_usage」，而那句「記得」就是它失效的地方——正式站 1,287 次 MCP 寫入裡，只有
16 次帶了用量。

所以把那一步從人的記性移到 PreToolUse hook 上。規格：Redmine #27061 是採集器，
#27059 是 MCP 側，plugin 側是 #27063；本檔隨 plugin 分發見 #27113 附加資訊「一個
中途發現、值得記錄的坑」。

三條不可以違反的規則：

1. 數字一律來自採集器的逐字輸出。這支腳本不解讀、不重算、不補零。
2. 拿不到就不要帶。採集器回 pending:false、逾時、或任何例外，都是安靜地什麼都
   不做——送一份全零的用量會在 Redmine 留下「這次工作沒有成本」的紀錄，那是一
   句假話，比沒有紀錄糟糕。
3. 永遠不要擋下寫入。記帳失敗的代價是少一筆用量；擋下寫入的代價是使用者的東西
   寫不進去。這與 plugin 那邊寫入點包 rescue 的理由是同一個。

本檔跟 collect.py 一起由 bootstrap.sh 複製到 ~/.claude/nineder/bin/（穩定位置，
理由與 bootstrap.sh／issue_context.sh 相同：組織派發的 plugin 路徑含 session id、
每次開對話都會變）。COLLECTOR 因此用同目錄下的 collect.py，不寫死路徑。
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

COLLECTOR = str(Path(__file__).resolve().parent / "collect.py")
# 上一次帶出去的是哪一段。用來擋同一輪內的重複帶（見 already_carried）。
STATE = os.path.expanduser("~/.claude/nineder/ai_usage_inline_state.json")
TIMEOUT = 25


def nothing():
    """什麼都不改，讓這次呼叫照原樣送出去。"""
    sys.exit(0)


def already_carried(payload):
    """同一段用量是不是剛剛才帶過。

    一輪裡連續兩次寫入時，第二次的 hook 有可能在第一次的結果還沒落進 transcript
    的空檔執行，於是採集器把同一段用量再算一次。那一段會被掛到兩個不同的 journal
    上，兩邊都收得下——plugin 的 409 只擋同一個 journal 重複記錄，擋不到這種。

    指紋取工作階段與五欄 token。同一段用量的指紋一定相同；真的又累積了新的用量，
    數字就會不一樣。
    """
    t = payload.get("tokens") or {}
    fingerprint = [
        payload.get("session"),
        t.get("input"), t.get("output"), t.get("cache_read"),
        t.get("cache_write_5m"), t.get("cache_write_1h"),
    ]
    try:
        with open(STATE) as fh:
            last = json.load(fh)
    except Exception:
        last = {}

    if last.get("fingerprint") == fingerprint:
        return True

    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as fh:
            json.dump({"fingerprint": fingerprint, "at": time.time()}, fh)
    except Exception:
        # 記不住就算了。最壞的情況是退回原本的行為，而不是擋下寫入。
        pass
    return False


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        nothing()

    tool_input = event.get("tool_input") or {}

    # 已經自己帶了就不要蓋掉。手動帶的那一份也是採集器輸出，而且呼叫端比這裡
    # 更清楚它要記的是哪一段。
    if tool_input.get("ai_usage"):
        nothing()

    # update_issue 不帶 notes 時多半只是改欄位，Redmine 仍然會產生 journal，
    # 用量掛上去是對的，所以不在這裡篩。真正該篩掉的是讀取類工具，那個由
    # settings.json 的 matcher 負責。

    if not os.path.exists(COLLECTOR):
        nothing()

    try:
        out = subprocess.run(
            [sys.executable, COLLECTOR, "--pending"],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except Exception:
        nothing()

    if out.returncode != 0:
        nothing()

    try:
        payload = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        nothing()

    if not payload.get("pending"):
        # 上次歸帳之後沒有新的用量。這是正常狀態，不是錯誤。
        nothing()

    if already_carried(payload):
        nothing()

    # 逐字送出採集器算出來的那一份，只去掉 pending 這個旗標——它是給這支腳本
    # 判斷用的，不是用量的一部分。
    payload.pop("pending", None)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": dict(tool_input, ai_usage=json.dumps(payload, ensure_ascii=False)),
        }
    }, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 這支腳本的任何失敗都不該讓使用者的寫入失敗。
        nothing()
