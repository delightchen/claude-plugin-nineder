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

#27641：MCP 新增 update_issue_note（修改既有 note）後，settings.json 的 matcher
要多收這一支，本檔不必改——它只負責把 ai_usage 併進 tool_input，不認工具名。
伺服器把那份用量記成一列「修改記錄」（issue_provenance_note_edits），不碰原
journal 那一列。該次修改被拒絕時，用量不會被消耗：collect.py 要看到成功回應裡
的 write_ledger 才把那一段結算，所以它仍留在下一次可帶出的區間。

本檔跟 collect.py 一起由 bootstrap.sh 複製到 ~/.claude/nineder/bin/（穩定位置，
理由與 bootstrap.sh／issue_context.sh 相同：組織派發的 plugin 路徑含 session id、
每次開對話都會變）。COLLECTOR 因此用同目錄下的 collect.py，不寫死路徑。

4.1.6：#27248 查出這支腳本原本九條放棄路徑全部靜默、不留任何痕跡——事後完全
分不清是「暫時沒有新用量」這種正常情況，還是採集器本身壞掉。這版在每一條放棄
路徑前補一行 SKIP_LOG，只記「為什麼放棄」，不影響前面三條規則：一樣不擋寫入、
一樣不補零、寫 log 本身失敗也一樣吞掉不影響原本行為。
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
# 每一次放棄夾帶的原因，一行一則 JSON。純診斷用途，不是用量資料的一部分。
SKIP_LOG = os.path.expanduser("~/.claude/nineder/ai_usage_inline_skip.log")
TIMEOUT = 25


def log_skip(reason, **extra):
    """記一行「這次為什麼沒有夾帶用量」。盡力而為，失敗就算了，不能影響 nothing() 的行為。"""
    try:
        os.makedirs(os.path.dirname(SKIP_LOG), exist_ok=True)
        entry = {"at": time.time(), "reason": reason}
        entry.update(extra)
        with open(SKIP_LOG, "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def nothing(reason=None, **extra):
    """什麼都不改，讓這次呼叫照原樣送出去；順便留一行為什麼放棄的診斷紀錄。"""
    if reason:
        log_skip(reason, **extra)
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
    except Exception as e:
        nothing("stdin_parse_error", error=str(e))

    tool_input = event.get("tool_input") or {}

    # 已經自己帶了就不要蓋掉。手動帶的那一份也是採集器輸出，而且呼叫端比這裡
    # 更清楚它要記的是哪一段。
    if tool_input.get("ai_usage"):
        nothing("already_has_ai_usage")

    # update_issue 不帶 notes 時多半只是改欄位，Redmine 仍然會產生 journal，
    # 用量掛上去是對的，所以不在這裡篩。真正該篩掉的是讀取類工具，那個由
    # settings.json 的 matcher 負責。

    if not os.path.exists(COLLECTOR):
        nothing("collector_missing", collector=COLLECTOR)

    try:
        out = subprocess.run(
            [sys.executable, COLLECTOR, "--pending"],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except Exception as e:
        nothing("collector_subprocess_error", error=str(e))

    if out.returncode != 0:
        nothing(
            "collector_nonzero_exit",
            returncode=out.returncode,
            stderr=(out.stderr or "")[-500:],
        )

    try:
        payload = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception as e:
        nothing(
            "collector_output_unparseable",
            error=str(e),
            stdout_tail=out.stdout[-500:],
        )

    if not payload.get("pending"):
        # 上次歸帳之後沒有新的用量。這是正常狀態，不是錯誤。
        nothing("no_pending_usage")

    if already_carried(payload):
        nothing("duplicate_fingerprint", session=payload.get("session"))

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
    except Exception as e:
        # 這支腳本的任何失敗都不該讓使用者的寫入失敗。
        nothing("unhandled_exception", error=str(e))
