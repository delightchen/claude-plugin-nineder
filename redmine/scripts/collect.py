#!/usr/bin/env python3
"""AI 用量採集器（Redmine #27061，日期／議題歸屬與每日台帳見 #27090）。

讀本機 Claude Code 的對話紀錄，算出每一段工作的 token 用量，歸屬到它
實際寫出的那一則 journal，再送進 Redmine 的 /ai_usage 端點（#27060）。

該端點現由 redmine_issue_provenance 提供（#27065）。路徑刻意沒有改：狀態檔記的是
「哪些區間已經送出去了」，換路徑本身不會出事，重建狀態檔才會 —— 已送過的區間會被
當成新的重送一次。所以舊路徑在過渡期原樣回應，這支程式與它的狀態檔都不必動。
舊路徑的移除時機記在 #27065。

為什麼要有這一段：沒有任何其他地方同時握有這兩樣東西。MCP 伺服器收到的
只有工具參數，看不到 token；模型看不到自己的用量。對話紀錄裡兩樣都有 ——
usage 欄位有 token，MCP 寫入回應的 write_ledger 有 journal 編號。

沒有 journal 可掛的部分（#27090）：一段用量結算的時機不再只有「遇到一次
MCP 寫入」，還多了兩種——跨過日期邊界、或換了一張不同的議題。三種結算都
會把累積量算清楚；前者送進既有的 /ai_usage/journals/:id，後兩者送進每日
台帳 /issue_provenance/daily（見 payload_for_daily 與 merge_daily_chunks）。

跑法：

    python3 collect.py              # 掃描並補記
    python3 collect.py --dry-run    # 只報告，不送出
    python3 collect.py --verbose    # 逐筆列出

需要 ~/.claude/nineder/redmine_api_key，或環境變數 REDMINE_API_KEY。

排程（#27090 驗收第九組）：不用 cron/launchd 固定時間跑，改成三個事件
觸發，都指向同一個「上次跑到現在」的動作，只是誰按下啟動鍵不同——
daily_trigger.py（每天第一個 session 啟動時）、resolved_trigger.py（議題
被推到 Resolved 時）、以及手動執行本檔。每次執行（無論由誰觸發、是否
--dry-run）都會在 ~/.claude/nineder/collector_runs.jsonl 留一行紀錄，
包含 trigger 來源、耗時、送出結果，失敗（含未預期的例外）也會留下來，
而不是安靜地什麼都沒發生——這是驗收第九組「靜默失敗等於沒有排程」
要求的落實方式：先把資料留下來，怎麼把失敗變得顯眼留待之後累積夠了
再決定。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

AI_NAME = "claude-code"
DEFAULT_BASE = "https://redmine.nineder.com"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
STATE_PATH = Path.home() / ".claude" / "nineder" / "ai_usage_state.json"
KEY_PATH = Path.home() / ".claude" / "nineder" / "redmine_api_key"
RUN_LOG_PATH = Path.home() / ".claude" / "nineder" / "collector_runs.jsonl"
DAILY_REJECTED_LOG_PATH = Path.home() / ".claude" / "nineder" / "daily_usage_rejected.jsonl"
LOCK_PATH = Path.home() / ".claude" / "nineder" / "collector.lock"

TOKEN_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
MCP_PREFIX = "mcp__nineder-redmine__"
CREATE_ISSUE_TOOL = MCP_PREFIX + "create_issue"

# 哪些工具呼叫「讀過」或「寫過」一張議題，以及議題編號放在呼叫參數的哪個欄位。
# 全部取自呼叫本身，不靠事後解析回應——呼叫當下就是事實，不必比對。
# create_issue 不在其中：它建立前沒有議題編號可填，改在 tool_result 的
# write_ledger 裡取得（見 write_ledger_entries）。
READ_ISSUE_TOOLS: dict[str, str] = {
    "get_issue": "issue_id",
    "get_issue_ai_usage": "issue_id",
    "list_issue_relations": "issue_id",
    "list_issue_reminders": "issue_id",
    "list_time_entries": "issue_id",
}
WRITE_ISSUE_TOOLS: dict[str, tuple[str, ...]] = {
    "update_issue": ("issue_id",),
    "delete_issue": ("issue_id",),
    "add_watcher": ("issue_id",),
    "remove_watcher": ("issue_id",),
    "add_time_entry": ("issue_id",),
    "create_issue_reminder": ("issue_id",),
    "update_issue_reminder": ("issue_id",),
    "delete_issue_reminder": ("issue_id",),
    "toggle_issue_reminder": ("issue_id",),
    # create_issue_relation 故意不在這裡：它一次呼叫同時指名兩張議題
    # （issue_id 與 issue_to_id），呼叫當下就記兩者會讓换題規則對著自己
    # 的兩個欄位互相觸發，把兩張都還沒累積到用量的那一刻切開，反而讓
    # 「從哪張連到哪張」這件事憑空消失。它的訊號改由回應的 write_ledger
    # （陣列，兩張議題各一份，各自帶著自己的 journal_id）取得，走既有的
    # journal 結算路徑，兩邊自然分開記——不需要在呼叫當下另外追蹤。
}


# ----------------------------------------------------------------------
# 狀態
# ----------------------------------------------------------------------

def load_state() -> dict:
    try:
        state = json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        state = {}
    state.setdefault("files", {})
    state.setdefault("posted", [])
    state.setdefault("pending", [])
    state.setdefault("daily_sent", {})
    state.setdefault("daily_pending", [])
    # 批次校正（#27163）用自己的一份 fingerprint，跟 state["files"] 分開追蹤：
    # 這支功能是後來加的，第一次跑的時候不能因為主掃描早就標記過某個檔案，
    # 就永遠不去補做這個檔案的批次校正。
    state.setdefault("correction_files", {})
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(STATE_PATH)  # 換名是原子的：中途掛掉不會留下半個狀態檔


LOCK_STALE_SECONDS = 600  # 正常一次執行遠低於這個數字，超過就當作持有者已經不在了


def acquire_lock() -> bool:
    """搶一把鎖，搶不到回傳 False。

    三個排程觸發點（session 開始、議題轉 Resolved、手動執行）彼此互不
    知情，同時各跑一次是常態，不是例外——沒有這道鎖，兩邊會各自對同一批
    對話紀錄重算、各自送出，落地順序顛倒時後蓋掉先，暫時性地把剛算好的
    較大總量蓋成較舊的較小值（#27090）。非阻塞：搶不到就立刻放棄，不排隊
    等待，因為下一次觸發本來就會補上這次沒做的事，排隊等待只是讓使用者
    多等一個用不到的行程。

    用 O_CREAT|O_EXCL 的原子建檔當鎖，不用 fcntl.flock——後者是 Windows
    完全沒有的模組（2026-09-16 發現：本檔一直隱性排除了 Windows，import
    fcntl 那一行會讓整支程式在還沒解析參數之前就先當掉）。O_EXCL 在
    POSIX 與 Windows 上語意一致，跨平台不必分兩套邏輯。

    代價：flock 隨行程結束自動釋放，這個做法不會——行程被強制中斷
    （SIGKILL、斷電）會留下鎖檔案。用檔案的 mtime 判斷是否棄置：正常一次
    執行是幾秒到幾十秒，超過 LOCK_STALE_SECONDS 還沒被清掉，就當作上一個
    持有者已經死亡，接手並重試一次；這個門檻夠寬，不會誤判正在跑的行程。
    """
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        try:
            age = time.time() - LOCK_PATH.stat().st_mtime
        except OSError:
            return False
        if age <= LOCK_STALE_SECONDS:
            return False
        try:
            LOCK_PATH.unlink()
        except OSError:
            return False
        return acquire_lock()  # 清掉棄置鎖後重試一次，理論上這次一定搶得到


def release_lock(held: bool) -> None:
    if not held:
        return
    try:
        LOCK_PATH.unlink()
    except OSError:
        pass


def api_key() -> str:
    key = os.environ.get("REDMINE_API_KEY")
    if key:
        return key.strip()
    try:
        return KEY_PATH.read_text().strip()
    except OSError:
        sys.exit(f"找不到 API key：設 REDMINE_API_KEY 或放進 {KEY_PATH}")


# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------

def normalise_model(model: str | None) -> str | None:
    """把 claude-haiku-4-5-20251001 收斂成 claude-haiku-4-5。

    價格是按模型家族定的，不是按快照日期。保留後綴會逼價目表為每一個
    快照各建一列，而那些列的費率完全相同 —— 多出來的只有對不上的風險。
    """
    if not model:
        return model
    return re.sub(r"-\d{8}$", "", model)


def new_bucket() -> dict:
    return {
        "tokens": dict.fromkeys(TOKEN_KEYS, 0),
        "requests": 0, "prompts": 0, "errors": 0,
        "model": None, "effort": None,
        # 這次累積期間讀過／寫過哪些議題——各自最多一張（見 note_issue）。
        "issues_read": set(), "issues_write": set(),
        # 這段累積量落在哪一天。取自紀錄本身的時間戳，不是執行採集器的
        # 當天：補跑三天前的資料不可以全部記成今天（#27090 驗收第一組）。
        "date": None,
    }


def usage_fields(bucket: dict) -> dict:
    """bucket 裡兩段結算路徑（journal／每日台帳）共用的那一份。"""
    return {
        "tokens": dict(bucket["tokens"]),
        "requests": bucket["requests"], "prompts": bucket["prompts"], "errors": bucket["errors"],
        "model": bucket["model"], "effort": bucket["effort"],
    }


def add_usage(bucket: dict, usage: dict, model, effort) -> None:
    cc = usage.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens", 0)
    w5m = cc.get("ephemeral_5m_input_tokens", 0)
    if not (w1h or w5m):
        # 舊紀錄沒有細分。全算 5 分鐘是保守的選擇：它的單價較低，寧可
        # 少報也不要憑空多報一筆沒有依據的 1 小時寫入。
        w5m = usage.get("cache_creation_input_tokens", 0)
    t = bucket["tokens"]
    t["input"] += usage.get("input_tokens", 0)
    t["output"] += usage.get("output_tokens", 0)
    t["cache_read"] += usage.get("cache_read_input_tokens", 0)
    t["cache_write_5m"] += w5m
    t["cache_write_1h"] += w1h
    bucket["requests"] += 1
    # 一段區間可能跨模型（中途換模型）。留最後一個：它是這段工作收尾時
    # 實際在用的那個，也是計價時最接近事實的選擇。
    if model:
        bucket["model"] = normalise_model(model)
    if effort:
        bucket["effort"] = effort


def is_empty(bucket: dict) -> bool:
    return bucket["requests"] == 0 and not any(bucket["tokens"].values())


def coerce_issue_id(raw) -> int | None:
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def date_of(ts) -> str | None:
    return ts[:10] if isinstance(ts, str) and len(ts) >= 10 else None


def finalize_chunk(bucket: dict) -> dict | None:
    """把目前累積的量結算成一筆「每日台帳」候選列。

    沒有內容或沒有日期就回 None——沒有東西可以送。歸屬依正面證據優先：
    寫過的議題比讀過的議題優先；兩者都沒有就是「無議題」。每個 bucket
    在結算當下最多只會記到一張議題（見 note_issue 的換題即結算），
    所以這裡不需要處理「多張議題選哪張」——那個決定在換題的當下就做完了。
    """
    if is_empty(bucket) or bucket["date"] is None:
        return None
    if bucket["issues_write"]:
        attribution, issue_id = "write", next(iter(bucket["issues_write"]))
    elif bucket["issues_read"]:
        attribution, issue_id = "read", next(iter(bucket["issues_read"]))
    else:
        attribution, issue_id = "none", None
    return {"date": bucket["date"], "attribution": attribution, "issue_id": issue_id,
            **usage_fields(bucket)}


def note_issue(bucket: dict, issue_id: int, kind: str, day_chunks: list[dict]) -> dict:
    """記下這次呼叫touch 到的議題；換了一張不同的議題時，先把目前累積的量
    結算掉，再開始記新的一張。

    這是 #27090 驗收第三組「讀過多張議題不可以任選一張」的實作方式：
    不是事後在一段混雜的用量裡挑一張，而是在「即將混雜」的那一刻就把
    界線畫下去——切開之後的兩段各自最多只認得一張議題，沒有真的被
    混在一起過的用量，也就不需要事後拆分或估計比例。
    """
    existing = bucket["issues_write"] | bucket["issues_read"]
    if existing and issue_id not in existing:
        chunk = finalize_chunk(bucket)
        if chunk is not None:
            day_chunks.append(chunk)
        carried_date = bucket["date"]
        bucket = new_bucket()
        bucket["date"] = carried_date
    (bucket["issues_write"] if kind == "write" else bucket["issues_read"]).add(issue_id)
    return bucket


def parse_transcript(path: Path) -> tuple[list[dict], dict | None, str | None, list[dict]]:
    """回傳（已歸屬的區間, 尾端未歸屬的殘餘, session_id, 每日台帳候選列）。

    演算法是「上一次結算到這一次之間」的累積差，但結算的時機有三種：

    1. 遇到帶 journal 編號的 MCP 寫入回應——結算進 segments（沿用既有的
       每則 journal 一份用量的路徑，未改變）。
    2. 遇到沒有 journal 可掛、但確實是一次寫入的回應（issue_id 有值、
       journal_id 是 null——多半是 create_issue，也可能是 Redmine 無法
       確定是哪一則 journal 的更新）——結算進 day_chunks，歸屬為 write。
    3. 換了一張不同的議題，或跨過日期邊界——結算進 day_chunks，歸屬依
       note_issue／finalize_chunk 的規則決定。

    leftover 維持舊有形狀（供 --pending 一次性帶出目前開著的那一段），
    day_chunks 是新增的，包含檔案掃描到最後那一段還沒結算的內容——
    每日台帳本來就是 upsert，把還在累積中的當日總量也送出去是對的。
    """
    seen_requests: set[str] = set()
    pending_tool: dict[str, str] = {}   # tool_use_id -> 工具名
    segments: list[dict] = []
    day_chunks: list[dict] = []
    bucket = new_bucket()
    session_id: str | None = None

    with path.open(errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            session_id = rec.get("sessionId") or session_id

            d = date_of(rec.get("timestamp"))
            if d is not None:
                if bucket["date"] is None:
                    bucket["date"] = d
                elif d != bucket["date"]:
                    chunk = finalize_chunk(bucket)
                    if chunk is not None:
                        day_chunks.append(chunk)
                    bucket = new_bucket()
                    bucket["date"] = d

            kind = rec.get("type")
            msg = rec.get("message") or {}

            if kind == "assistant":
                # 這一則的工具呼叫先記，這則自己的 usage 後加：換題要切的是
                # 「換題之前」累積的量，不能連這一則自己的用量都算進舊的
                # 那張議題——不然新議題的第一則請求，用量會被記到舊議題上。
                for blk in msg.get("content") or []:
                    if not (isinstance(blk, dict) and blk.get("type") == "tool_use"):
                        continue
                    name = str(blk.get("name", ""))
                    if not name.startswith(MCP_PREFIX):
                        continue
                    pending_tool[blk["id"]] = name
                    short = name[len(MCP_PREFIX):]
                    inp = blk.get("input") or {}
                    if short in READ_ISSUE_TOOLS:
                        iid = coerce_issue_id(inp.get(READ_ISSUE_TOOLS[short]))
                        if iid is not None:
                            bucket = note_issue(bucket, iid, "read", day_chunks)
                    elif short in WRITE_ISSUE_TOOLS:
                        for field in WRITE_ISSUE_TOOLS[short]:
                            iid = coerce_issue_id(inp.get(field))
                            if iid is not None:
                                bucket = note_issue(bucket, iid, "write", day_chunks)

                rid = rec.get("requestId")
                usage = msg.get("usage") or {}
                # 一則訊息含多個 content block 時會拆成多行寫入，每行都帶
                # 完整的 usage。實測重複率 54%：不去重，帳目虛增一倍。
                if rid and usage and rid not in seen_requests:
                    seen_requests.add(rid)
                    add_usage(bucket, usage, msg.get("model"), rec.get("effort"))

            elif kind == "user":
                content = msg.get("content")
                if isinstance(content, str) and not rec.get("isMeta"):
                    bucket["prompts"] += 1
                    continue
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict) or blk.get("type") != "tool_result":
                        continue
                    if blk.get("is_error"):
                        bucket["errors"] += 1
                    for entry in write_ledger_entries(blk, pending_tool):
                        bucket = note_issue(bucket, entry["issue_id"], "write", day_chunks)
                        jid = entry["journal_id"]
                        if jid is not None:
                            if not is_empty(bucket):
                                segments.append({"journal_id": jid, **usage_fields(bucket)})
                            carried_date = bucket["date"]
                            bucket = new_bucket()
                            bucket["date"] = carried_date
                        else:
                            # 確實寫入過，但沒有 journal 可掛（多半是 create_issue）。
                            # 這是有正面證據的歸屬，送進每日台帳而不是留著等下一次
                            # MCP 寫入把它糊在不相干的那一則上（#27090 驗收第五組）。
                            chunk = finalize_chunk(bucket)
                            if chunk is not None:
                                day_chunks.append(chunk)
                            carried_date = bucket["date"]
                            bucket = new_bucket()
                            bucket["date"] = carried_date

    leftover = None if is_empty(bucket) else usage_fields(bucket)
    tail_chunk = finalize_chunk(bucket)
    if tail_chunk is not None:
        day_chunks.append(tail_chunk)
    return segments, leftover, session_id, day_chunks


def write_ledger_entries(block: dict, pending_tool: dict) -> list[dict]:
    """MCP 寫入回應裡的 write_ledger，解析成 [{issue_id, journal_id}, ...]。

    可能是單一物件（update_issue／create_issue／delete_issue 的形狀），也
    可能是陣列（create_issue_relation 一次在兩張議題上都留下痕跡）。伺服器
    有時無法確定是哪一則 journal（它靠寫入前後比對），那時 journal_id 為
    null——那是「無法確定」，不是零。非物件、非陣列、缺 issue_id，或整段
    不是合法 JSON，一律回傳空列表——沒有可靠證據就當作沒有，而不是猜。
    """
    if block.get("tool_use_id") not in pending_tool:
        return []
    content = block.get("content")
    if isinstance(content, list):
        text = next((c.get("text", "") for c in content
                     if isinstance(c, dict) and c.get("type") == "text"), "")
    else:
        text = content if isinstance(content, str) else ""
    if "write_ledger" not in text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        return []
    if not isinstance(parsed, dict):
        return []
    ledger = parsed.get("write_ledger")
    if isinstance(ledger, dict):
        raw_entries = [ledger]
    elif isinstance(ledger, list):
        raw_entries = ledger
    else:
        return []

    entries = []
    for e in raw_entries:
        if not isinstance(e, dict):
            continue
        issue_id = coerce_issue_id(e.get("issue_id"))
        if issue_id is None:
            continue
        jid = e.get("journal_id")
        try:
            jid = int(jid) if jid is not None else None
        except (TypeError, ValueError):
            jid = None
        entries.append({"issue_id": issue_id, "journal_id": jid})
    return entries


def journal_id_of(block: dict, pending_tool: dict) -> int | None:
    """向下相容用：只要第一筆 write_ledger 項目的 journal 編號。"""
    entries = write_ledger_entries(block, pending_tool)
    return entries[0]["journal_id"] if entries else None


# ----------------------------------------------------------------------
# 批次建立子票的回溯校正（#27163）
#
# 只在這裡結算：即時 hook（ai_usage_inline.py）與上面 parse_transcript 的
# day_chunks，一遇到讀寫其他議題就切一段——那是給「單張議題」的即時歸因用
# 的，套在「一次連續建立好幾張子票」上會把中途讀参照票的量另外記走一份，
# 跟每日台帳的 read 歸因重複計費。這裡的规則不同（2026-09-17 定案）：
# 中途讀寫的任何議題，token 一律留在累積池裡，只在遇到下一次 create_issue
# 時才結算一段——這才是「這批子票花了多少」該有的量。
# ----------------------------------------------------------------------

def parse_creation_events(path: Path) -> tuple[list[dict], str | None]:
    """單一 session 內，依序取出每一次 create_issue 呼叫的累積用量與 parent_id。

    parent_id 取自呼叫當下的參數（不是事後補的 relates）——建立子票時，
    母票多半已經在同一批裡建好，parent_id 當下就填得出來，不必等事後補
    關聯才能判斷樹狀關係。回傳的每一筆事件都帶著「上一次 create_issue（或
    session 開頭）到這一次之間」累積的全部用量，不管中途穿插了什麼。
    """
    events: list[dict] = []
    pending_tool: dict[str, str] = {}
    pending_input: dict[str, dict] = {}
    seen_requests: set[str] = set()
    bucket = new_bucket()
    session_id: str | None = None

    with path.open(errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            session_id = rec.get("sessionId") or session_id

            d = date_of(rec.get("timestamp"))
            if d is not None and bucket["date"] is None:
                bucket["date"] = d

            kind = rec.get("type")
            msg = rec.get("message") or {}

            if kind == "assistant":
                for blk in msg.get("content") or []:
                    if not (isinstance(blk, dict) and blk.get("type") == "tool_use"):
                        continue
                    name = str(blk.get("name", ""))
                    pending_tool[blk["id"]] = name
                    if name == CREATE_ISSUE_TOOL:
                        pending_input[blk["id"]] = blk.get("input") or {}

                rid = rec.get("requestId")
                usage = msg.get("usage") or {}
                if rid and usage and rid not in seen_requests:
                    seen_requests.add(rid)
                    add_usage(bucket, usage, msg.get("model"), rec.get("effort"))

            elif kind == "user":
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict) or blk.get("type") != "tool_result":
                        continue
                    tool_use_id = blk.get("tool_use_id")
                    if pending_tool.get(tool_use_id) != CREATE_ISSUE_TOOL:
                        continue
                    for entry in write_ledger_entries(blk, pending_tool):
                        if entry["journal_id"] is not None:
                            continue  # 不是这支函式管的形狀（create_issue 一律沒有 journal）
                        events.append({
                            "issue_id": entry["issue_id"],
                            # MCP 工具參數叫 parent_issue_id，不是 parent_id
                            # （create_issue schema：parent_issue_id 建子票）。
                            "parent_id": coerce_issue_id(
                                (pending_input.get(tool_use_id) or {}).get("parent_issue_id")),
                            **usage_fields(bucket),
                        })
                        carried_date = bucket["date"]
                        bucket = new_bucket()
                        bucket["date"] = carried_date

    return events, session_id


def build_creation_tree(events: list[dict]) -> dict[int, dict]:
    """依 events 的 parent_id 建父子關係，只認同一批裡的邊。

    parent_id 指到批次外的議題（母票是早就存在的舊票，不是這次連著建的）
    視同這個節點在這批次裡沒有母票——它在這批次裡自己就是一個根，不是孤兒，
    也不會因為找不到母票而被排除在校正範圍外。
    """
    by_id = {e["issue_id"]: dict(e, children=[]) for e in events}
    for e in events:
        pid = e["parent_id"]
        if pid is not None and pid in by_id and pid != e["issue_id"]:
            by_id[pid]["children"].append(e["issue_id"])
    return by_id


def _height(issue_id: int, by_id: dict, cache: dict[int, int]) -> int:
    if issue_id in cache:
        return cache[issue_id]
    children = by_id[issue_id]["children"]
    h = 0 if not children else 1 + max(_height(c, by_id, cache) for c in children)
    cache[issue_id] = h
    return h


def split_evenly(members: list[dict], count: int) -> list[dict]:
    """把 members 的用量加總，均分成 count 份，整數不留餘數。

    除不盡時前面幾份多拿 1（哪一份拿到不重要——反正這一層本來就是均分，
    不嘗試分出每一張的精確份額），確保加總起來剛好等於總量，不會因為
    整數除法讓校正後的總量比校正前少一點。
    """
    total_tokens = {k: sum(m["tokens"][k] for m in members) for k in TOKEN_KEYS}
    totals = {
        "requests": sum(m["requests"] for m in members),
        "prompts": sum(m["prompts"] for m in members),
        "errors": sum(m["errors"] for m in members),
    }
    model = next((m["model"] for m in reversed(members) if m.get("model")), None)
    effort = next((m["effort"] for m in reversed(members) if m.get("effort")), None)

    def distribute(total: int) -> list[int]:
        base, rem = divmod(total, count)
        return [base + (1 if i < rem else 0) for i in range(count)]

    token_shares = {k: distribute(v) for k, v in total_tokens.items()}
    other_shares = {k: distribute(v) for k, v in totals.items()}

    return [
        {"tokens": {k: token_shares[k][i] for k in TOKEN_KEYS},
         **{k: other_shares[k][i] for k in other_shares},
         "model": model, "effort": effort}
        for i in range(count)
    ]


def compute_batch_correction(events: list[dict]) -> dict[int, dict]:
    """#27163 定案演算法：葉節點用序列差值，往上每一層均分剩下的池子。

    葉節點（這批裡自己沒有子票的）直接拿它自己那段序列差值——events 裡
    每一筆本來就是「上一次 create_issue 到這一次」的原始累積量。再往上每
    一層，不嘗試切出每一張母票各自精確的視窗（建立順序可能交錯，切不出
    乾淨的邊界）：同一層的所有票，不論屬於哪一棵子樹，直接把「這些票自己
    那段原始序列差值」（by_id[iid] 裡還沒被下面層級動過的原始值）合併、
    均分。之所以不必再另外減去底下各層的加總——描述裡「這一層的累積減去
    底下所有層級」——是因為底下各層的份額，本來就是從它們自己那段原始序列
    差值切出來的，從沒進過這一層節點自己的原始序列差值裡；兩邊本來就沒有
    重疊，不需要真的做一次減法。
    """
    by_id = build_creation_tree(events)
    height_cache: dict[int, int] = {}
    heights = {iid: _height(iid, by_id, height_cache) for iid in by_id}
    max_h = max(heights.values(), default=-1)

    final: dict[int, dict] = {}
    for h in range(max_h + 1):
        ids = [iid for iid in by_id if heights[iid] == h]
        if not ids:
            continue
        if h == 0:
            for iid in ids:
                e = by_id[iid]
                final[iid] = {"tokens": dict(e["tokens"]), "requests": e["requests"],
                               "prompts": e["prompts"], "errors": e["errors"],
                               "model": e["model"], "effort": e["effort"]}
        else:
            shares = split_evenly([by_id[iid] for iid in ids], len(ids))
            for iid, share in zip(ids, shares):
                final[iid] = share
    return final


def delete_issue_usage(base: str, key: str, issue_id: int, timeout: float = 15.0) -> dict:
    """清空這張議題「自己的」用量，校正前的第一步（見 DELETE /issue_provenance/issues/:id）。"""
    req = urllib.request.Request(
        f"{base}/issue_provenance/issues/{issue_id}.json",
        headers={"X-Redmine-API-Key": key}, method="DELETE",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def post_issue_usage(base: str, key: str, issue_id: int, body: dict, timeout: float = 15.0) -> str:
    """回傳 'ok'、'exists'，或拋出例外——跟 post() 對 journal 的那支同一套慣例。"""
    req = urllib.request.Request(
        f"{base}/issue_provenance/issues/{issue_id}.json",
        data=json.dumps(body).encode(),
        headers={"X-Redmine-API-Key": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return "ok"
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return "exists"
        raise


def apply_batch_corrections(final: dict[int, dict], session_id: str, base: str, key: str,
                             dry_run: bool, verbose: bool) -> dict:
    """對 compute_batch_correction 算出來的每一張議題做 DELETE＋POST，回傳計數。

    手動的 --correct-batch 與排程流程的自動批次校正共用這一支——兩邊唯一的
    差別是「怎麼取得 events」，送出的邏輯不重複寫兩份。
    """
    corrected = skipped = failed = 0
    for issue_id, usage in final.items():
        total = sum(usage["tokens"].values())
        if dry_run or verbose:
            suffix = "（dry-run，未送出）" if dry_run else ""
            print(f"  議題 #{issue_id}：{total:,} token{suffix}")
        if dry_run:
            continue
        try:
            delete_issue_usage(base, key, issue_id)
            result = post_issue_usage(base, key, issue_id, payload_for(usage, session_id))
            if result == "exists":
                skipped += 1
            else:
                corrected += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if verbose:
                print(f"  議題 #{issue_id}：失敗 {exc}")
    return {"corrected": corrected, "skipped": skipped, "failed": failed}


def run_batch_correction(args) -> dict:
    """--correct-batch 的主流程：手動、立即校正指定的一個 session。

    範圍只到「自己剛剛建立的那批」（#27163 拍板）：讀取哪個 session 的取法
    跟 --pending 一致，不做跨人歷史回填，所以不需要 clear_ai_usage 或 admin。
    跟排程流程（_scan_and_send）不一樣的地方：這裡是使用者明確要求「現在就
    校正這個」，所以不管 state["correction_files"] 裡的 fingerprint 有沒有
    對上，一律重算重送；送完才回頭補上 fingerprint，讓下一次排程掃描不會
    為了同一批內容再白做一次 DELETE＋POST。
    """
    if args.session:
        candidates = list(PROJECTS_DIR.glob(f"*/{args.session}.jsonl"))
        if not candidates:
            print(json.dumps({"error": f"找不到工作階段 {args.session}"}, ensure_ascii=False))
            return {"exit_code": 1}
        path = candidates[0]
    else:
        files = sorted(PROJECTS_DIR.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not files:
            print(json.dumps({"error": "找不到任何對話紀錄"}, ensure_ascii=False))
            return {"exit_code": 1}
        path = files[-1]

    events, session_id = parse_creation_events(path)
    if not events or session_id is None:
        print("這個工作階段沒有找到任何 create_issue 事件，無需校正")
        return {"exit_code": 0, "issues": 0}

    final = compute_batch_correction(events)
    key = "" if args.dry_run else api_key()
    result = apply_batch_corrections(final, session_id, args.base, key, args.dry_run, args.verbose)

    print(f"session {session_id}：{len(events)} 個建立事件，{len(final)} 張議題")
    if not args.dry_run:
        print(f"已校正 {result['corrected']}，已存在略過 {result['skipped']}，失敗 {result['failed']}")
        state = load_state()
        stat = path.stat()
        state["correction_files"][str(path)] = f"{stat.st_mtime_ns}:{stat.st_size}"
        save_state(state)
    return {"exit_code": 1 if result["failed"] else 0, "issues": len(final), **result}


# ----------------------------------------------------------------------
# 送出
# ----------------------------------------------------------------------

def payload_for(seg: dict, session_id: str) -> dict:
    return {
        "name": AI_NAME,
        "model": seg.get("model") or "unknown",
        "effort": seg.get("effort"),
        "session": session_id,
        "prompts": seg["prompts"],
        "requests": seg["requests"],
        "errors": seg["errors"],
        "tokens": seg["tokens"],
    }


def payload_for_daily(chunk: dict, session_id: str) -> dict:
    return {
        "usage_date": chunk["date"],
        "ai_session": session_id,
        "issue_id": chunk["issue_id"],
        "attribution": chunk["attribution"],
        "ai_name": AI_NAME,
        "ai_model": chunk.get("model") or "unknown",
        "ai_effort": chunk.get("effort"),
        "ai_prompts": chunk["prompts"],
        "ai_requests": chunk["requests"],
        "ai_errors": chunk["errors"],
        "tokens": chunk["tokens"],
    }


ATTRIBUTION_RANK = {"none": 0, "read": 1, "write": 2}


def merge_daily_chunks(chunks: list[dict]) -> list[dict]:
    """同一份對話紀錄裡，同一天、同一張議題的多段合併成一列。

    合併鍵刻意不含歸屬（attribution）：Redmine 那張表的唯一鍵是「日期、
    使用者、session、議題」，不含歸屬。同一天同一張議題如果先讀後寫（或
    分屬當天兩段不同時段各自結算），在這裡沒合併的話會產生兩筆本機看似
    不同、但 Redmine 眼裡是同一格的列——同一批送出去就直接互撞，被 422
    整批拒絕（實測事故：780 筆的批次因此全軍覆沒，來源正是這裡）。

    歸屬合併採跟單一 bucket 結算時同一套優先序：write 蓋過 read 蓋過
    none——當天只要有一次寫入證據，就不該讓這天這張議題的紀錄退回成
    「僅憑讀取推論」。

    每日台帳是 upsert（設成最新值，不是相加），送兩筆同一組維度的資料會讓
    後一筆蓋掉前一筆——所以送出之前要先在這裡把它們加總，只送一筆。
    """
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for c in chunks:
        key = (c["date"], c["issue_id"])
        if key not in merged:
            merged[key] = {**c, "tokens": dict(c["tokens"])}
            order.append(key)
        else:
            m = merged[key]
            for k in TOKEN_KEYS:
                m["tokens"][k] += c["tokens"][k]
            m["requests"] += c["requests"]
            m["prompts"] += c["prompts"]
            m["errors"] += c["errors"]
            if ATTRIBUTION_RANK[c["attribution"]] > ATTRIBUTION_RANK[m["attribution"]]:
                m["attribution"] = c["attribution"]
            if c.get("model"):
                m["model"] = c["model"]
            if c.get("effort"):
                m["effort"] = c["effort"]
    return [merged[k] for k in order]


def collapse_daily_items(items: list[dict]) -> list[dict]:
    """最後一道防線：合併任何仍然撞在同一個 Redmine 維度（日期、session、
    議題）上的候選列，不管它們是從哪個檔案、哪次執行累積來的。

    merge_daily_chunks 已經在單一檔案內解決了「同一天同一張議題但歸屬
    不同」的碰撞——那是實測發生過、把整批 780 筆一次打掉的根因。這裡
    再做一層跨檔案、跨執行的保險：本機的 daily_sent 去重鍵含檔案路徑與
    歸屬，理論上兩個不同來源（不同檔案、或這次新算的跟上次沒送成功的
    pending）仍有可能湊出同一組伺服器維度。與其假設不會發生，不如在
    真的送出前再做一次防呆——合併的代價趨近於零，撞上的代價是整批
    被 422 打掉。
    """
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for item in items:
        p = item["payload"]
        dim = (p["usage_date"], p["ai_session"], p["issue_id"])
        if dim not in merged:
            merged[dim] = {"keys": [item["key"]], "payload": dict(p, tokens=dict(p["tokens"]))}
            order.append(dim)
        else:
            m = merged[dim]
            m["keys"].append(item["key"])
            mp, ip = m["payload"], p
            for k in TOKEN_KEYS:
                mp["tokens"][k] += ip["tokens"][k]
            mp["ai_prompts"] += ip["ai_prompts"]
            mp["ai_requests"] += ip["ai_requests"]
            mp["ai_errors"] += ip["ai_errors"]
            if ATTRIBUTION_RANK[ip["attribution"]] > ATTRIBUTION_RANK[mp["attribution"]]:
                mp["attribution"] = ip["attribution"]
            if ip.get("ai_model"):
                mp["ai_model"] = ip["ai_model"]
            if ip.get("ai_effort"):
                mp["ai_effort"] = ip["ai_effort"]

    out = []
    for dim in order:
        m = merged[dim]
        fp = json.dumps([m["payload"]["tokens"], m["payload"]["ai_requests"],
                          m["payload"]["ai_prompts"], m["payload"]["ai_errors"]],
                         sort_keys=True)
        # 保留每一個原始 key：送成功後要讓它們各自標記為「已送出」，
        # 不然下次重新掃描各自的來源檔案時，誰都對不上這個合併後的新
        # 鍵，於是每次都被誤判成新資料、無止盡地重送（資料不會錯，
        # 只是白工）。key 仍取第一個當作這個項目的代表鍵。
        out.append({"key": m["keys"][0], "merged_keys": m["keys"],
                    "fingerprint": fp, "payload": m["payload"]})
    return out


def post(base: str, key: str, journal_id: int, body: dict, timeout: float = 15.0) -> str:
    """回傳 'ok'、'exists'，或拋出例外讓呼叫端留待重試。"""
    req = urllib.request.Request(
        f"{base}/ai_usage/journals/{journal_id}.json",
        data=json.dumps(body).encode(),
        headers={"X-Redmine-API-Key": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return "ok"
    except urllib.error.HTTPError as exc:
        # 409 表示這一則已經有用量記錄了。那是正常結果，不是失敗：重跑
        # 採集器本來就該是安全的，把它當錯誤會讓每次執行都堆一批假警報。
        if exc.code == 409:
            return "exists"
        raise


def post_daily(base: str, key: str, rows: list[dict], timeout: float = 20.0) -> dict:
    """送一批每日台帳列。伺服器整批一個交易——任何一列不合法就整批拒絕。

    回傳 {"inserted":, "updated":} 是成功；{"ok": False, "error": ...} 是
    伺服器判定資料本身不合法（422，例如指到不存在的議題），這種不會因為
    重送而變好，呼叫端不應該無限重試同一批；其他錯誤（網路、5xx）往外拋，
    留給呼叫端決定要不要重試。
    """
    req = urllib.request.Request(
        f"{base}/issue_provenance/daily.json",
        data=json.dumps({"rows": rows}).encode(),
        headers={"X-Redmine-API-Key": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 422:
            body = exc.read().decode(errors="replace")
            try:
                msg = json.loads(body).get("error", body)
            except ValueError:
                msg = body
            return {"ok": False, "error": msg}
        raise


ROW_ERROR_RE = re.compile(r"^row (\d+):")


class DailyPostError(Exception):
    """post_daily_resilient 送出時遇到網路／伺服器暫時性錯誤（非 422）往外拋。

    附帶 remaining（還沒送出、該留到下次重試）與 rejected（已經在這次重試
    迴圈裡確定是哪一列資料本身有問題、記錄下原因、不會再回到 pending 裡）—
    呼叫端需要兩者才能正確更新狀態，不能只知道「失敗了」。
    """

    def __init__(self, remaining: list[dict], rejected: list[tuple[dict, str]], message: str) -> None:
        super().__init__(message)
        self.remaining = remaining
        self.rejected = rejected


def post_daily_resilient(
    base: str, key: str, items: list[dict], timeout: float = 20.0
) -> tuple[list[dict], list[tuple[dict, str]], dict | None, str | None]:
    """送每日台帳整批，一列一列地把「資料本身不合法」的列隔離掉。

    伺服器整批一個交易，任何一列不合法就整批 422——這是伺服器該有的行為
    （半套資料比沒有資料更難查）。但呼叫端如果因此把整批當成失敗丟掉，
    後果是同一批裡其他合法的用量也跟著消失：來源檔案在送出結果出爐前
    就已經被標成「已掃描」（見 _scan_and_send），這些列不會再被重新產生，
    一去不回（#27090 驗收第十組實測踩到：2026-09-19 當天 6 次批次因為單一
    列指向不存在的議題而整批遺失）。

    422 的錯誤訊息固定是「row N: 原因」（N 是這次送出的陣列位置，見
    DailyUsage.prepare／guard_against_duplicates!），這個位置在整批裡是
    確定的、不是猜的，所以可以把第 N 列單獨挑出來隔離，其餘的重新送一次。
    隔離不等於補救——議題真的不存在就是救不回來，但至少被記下來、
    不是悄悄消失，而且不會拖累同一批裡其他本來合法的列。

    如果錯誤訊息認不出格式（例如「rows is empty」這種整批性、不是針對
    某一列的錯誤），沒辦法只挑一列隔離而不誤殺其他列，此時整批原樣
    回傳給呼叫端當結構性錯誤處理，不在這裡瞎猜。

    回傳 (sent_items, rejected, result, structural_error)：
    - sent_items：最後一次成功送出的那些 item（呼叫端拿去標記 daily_sent）。
    - rejected：[(item, 原因), ...]，被隔離掉、不會再重試的列。
    - result：成功時是伺服器回應的 {"inserted":, "updated":}；全部被隔離掉
      而完全沒有東西可送時是 None。
    - structural_error：認不出是哪一列時的錯誤訊息；其餘情況為 None。
    """
    remaining = list(items)
    rejected: list[tuple[dict, str]] = []
    while remaining:
        try:
            result = post_daily(base, key, [it["payload"] for it in remaining], timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — 網路/5xx，留給呼叫端決定要不要重試
            raise DailyPostError(remaining, rejected, str(exc)) from exc

        if result.get("ok") is not False:
            return remaining, rejected, result, None

        match = ROW_ERROR_RE.match(str(result.get("error", "")))
        idx = int(match.group(1)) if match else -1
        if match is None or not 0 <= idx < len(remaining):
            return [], rejected, None, result.get("error")

        rejected.append((remaining.pop(idx), result["error"]))

    return [], rejected, None, None


def record_rejected_daily_rows(rejected: list[tuple[dict, str]]) -> None:
    """把被隔離的每日台帳列連同原因寫進一份獨立的紀錄檔。

    排程觸發時沒有人盯著終端機，只印在標準輸出的東西會隨下次執行的
    輸出被沖掉。這份檔案讓「哪一列被隔離、為什麼」在事後還查得到——
    不遺失指的是「不悄悄消失」，不是「一定要送得進去」（議題真的不存在
    就是送不進去）。寫入失敗（例如磁碟滿了）不應該讓採集器本身也跟著
    報錯，所以吞掉例外，跟 log_run 的做法一致。
    """
    if not rejected:
        return
    try:
        DAILY_REJECTED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DAILY_REJECTED_LOG_PATH.open("a") as fh:
            for item, reason in rejected:
                fh.write(json.dumps({
                    "rejected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "key": item.get("key"),
                    "reason": reason,
                    "payload": item.get("payload"),
                }, ensure_ascii=False) + "\n")
    except OSError:
        pass


def log_run(record: dict) -> None:
    """每次執行都留一行紀錄，不管是誰觸發、成功還是失敗。

    #27090 排程改走事件觸發（session 開始、議題轉 Resolved、手動執行），
    不是固定時間的 cron；「失敗時看得出來」因此不能靠人盯著終端機，只能
    先把結構化的執行紀錄留下來——之後要怎麼把失敗變顯眼（跳出警告、發
    通知），等累積夠了再決定，這裡只負責不遺漏。寫入失敗（例如磁碟滿了）
    本身不應該讓採集器的結果跟著報錯，所以吞掉例外。
    """
    try:
        RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with RUN_LOG_PATH.open("a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ----------------------------------------------------------------------
# 當前區間（寫 note 時一併帶上）
# ----------------------------------------------------------------------

def emit_pending(session: str | None) -> int:
    """印出「上次歸帳到現在」的用量，格式就是 plugin 標頭吃的那一份。

    這是排程的替代方案：與其事後掃描補記，不如在寫 note 的當下把數字
    一起帶上 —— journal 編號在那個當下才是確定的，而數字由這支腳本算，
    不是由模型申報它看不到的東西。
    """
    if session:
        candidates = list(PROJECTS_DIR.glob(f"*/{session}.jsonl"))
        if not candidates:
            print(json.dumps({"error": f"找不到工作階段 {session}"}, ensure_ascii=False))
            return 1
        path = candidates[0]
    else:
        files = sorted(PROJECTS_DIR.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not files:
            print(json.dumps({"error": "找不到任何對話紀錄"}, ensure_ascii=False))
            return 1
        # 最近異動的那一個就是正在進行的這一段。
        path = files[-1]

    _segments, leftover, session_id, _day_chunks = parse_transcript(path)
    if leftover is None or session_id is None:
        # 上一次寫入之後還沒有新的用量。回一個明確的空，而不是一份全是
        # 零的payload —— 送出零會在 Redmine 留下「這則 note 沒花任何成本」
        # 的紀錄，那是一句和事實不同的話。
        print(json.dumps({"pending": False}, ensure_ascii=False))
        return 0

    print(json.dumps({"pending": True, **payload_for(leftover, session_id)}, ensure_ascii=False))
    return 0


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="AI 用量採集器（Redmine #27061／#27090）")
    ap.add_argument("--dry-run", action="store_true", help="只報告，不送出")
    ap.add_argument("--verbose", action="store_true", help="逐筆列出")
    ap.add_argument("--base", default=os.environ.get("REDMINE_BASE_URL", DEFAULT_BASE))
    ap.add_argument("--pending", action="store_true",
                    help="輸出當前工作階段「上次歸帳到現在」的用量（JSON），供寫 note 時一併帶上")
    ap.add_argument("--session", help="指定工作階段；省略時取最近異動的那一個")
    ap.add_argument("--correct-batch", action="store_true",
                    help="回溯校正指定 session 裡連續建立的那一批子票的用量分攤（#27163）")
    ap.add_argument("--baseline", action="store_true",
                    help="把目前所有可歸屬的區間標記為已處理但不送出，作為「從此刻開始」的起點")
    ap.add_argument("--trigger", default="manual",
                    help="這次執行是誰觸發的（manual／session_start／issue_resolved／…），"
                         "只用來寫進執行紀錄，不影響行為")
    args = ap.parse_args()

    if args.pending:
        return emit_pending(args.session)

    if args.correct_batch:
        # 手動、一次性的動作，不是排程掃描——不搶鎖也不寫執行紀錄，跟
        # --pending 一樣的道理：它不碰 STATE_PATH，跟自動掃描不會互相踩到。
        return run_batch_correction(args)["exit_code"]

    started = time.time()
    lock = acquire_lock()
    if not lock:
        # 三個觸發點（session 開始、議題轉 Resolved、手動執行）彼此不知道
        # 對方存不存在，同時各跑一次是常態而不是例外。兩邊都對著同一批
        # 對話紀錄重算，算出來的值理論上一樣，蓋掉彼此不會錯；但落地順序
        # 顛倒時，先算好、後落地的那次可能把後算好、先落地的那次覆蓋成
        # 比較舊的數字——當下不算錯，但暫時性地少算了一段。與其冒這個
        # 風險，同一時間只准一個真的跑，其餘的直接讓下一次觸發去補。
        log_run({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "trigger": args.trigger, "dry_run": args.dry_run,
            "ok": True, "skipped_lock_held": True,
            "duration_s": round(time.time() - started, 2),
        })
        print("另一個採集器正在執行中，這次跳過（避免同時上傳互相覆蓋）")
        return 0

    try:
        try:
            result = _scan_and_send(args)
        except Exception as exc:  # noqa: BLE001
            # 排程改走事件觸發，沒有人盯著終端機——例外往外拋一樣要被記下來，
            # 不能只在拋出的當下印一次就消失（#27090 驗收第九組）。
            log_run({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "trigger": args.trigger, "dry_run": args.dry_run,
                "ok": False, "crashed": True, "error": str(exc),
                "duration_s": round(time.time() - started, 2),
            })
            raise
    finally:
        release_lock(lock)

    result["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result["trigger"] = args.trigger
    result["dry_run"] = args.dry_run
    result["duration_s"] = round(time.time() - started, 2)
    result["ok"] = result["exit_code"] == 0
    log_run(result)
    return result["exit_code"]


def _scan_and_send(args) -> dict:
    state = load_state()
    posted = set(state.get("posted", []))
    daily_sent: dict[str, str] = state.get("daily_sent", {})
    correction_tracked: dict[str, str] = state["correction_files"]
    key = "" if args.dry_run else api_key()

    files = sorted(PROJECTS_DIR.glob("*/*.jsonl"))
    scanned = skipped = 0
    to_send: list[tuple[int, dict]] = []
    # 每一筆：{"key":, "fingerprint":, "payload":}。key 以檔案路徑＋日期／歸屬／
    # 議題組成，用來判斷這筆資料自上次送出後有沒有變過，不必每次都重送。
    daily_items: list[dict] = []
    # 每一筆：(session_id, compute_batch_correction 算出來的 {issue_id: usage} 字典)。
    batch_todo: list[tuple[str, dict[int, dict]]] = []

    for path in files:
        stat = path.stat()
        fingerprint = f"{stat.st_mtime_ns}:{stat.st_size}"
        main_stale = state["files"].get(str(path)) != fingerprint
        # 批次校正（#27163）用自己的一份 fingerprint：這支功能是後來才加的，
        # 不能因為主掃描早就標記過某個檔案沒動過，就永遠不去補做這個檔案的
        # 批次校正——兩者獨立判斷，各自決定要不要重新處理這個檔案。
        correction_stale = correction_tracked.get(str(path)) != fingerprint
        if not main_stale and not correction_stale:
            skipped += 1
            continue

        # 檔案沒動過就整個跳過，動過的整份重掃，而不是從上次的位移接續:
        # 累積差要從區間開頭算起，從中途接手會把一段拆成兩半各記一次。
        # 重複解析的成本遠小於算錯的代價，而且 posted／daily_sent 會擋下重送。
        if main_stale:
            segments, _leftover, session_id, day_chunks = parse_transcript(path)
            scanned += 1
            if session_id is not None:
                for seg in segments:
                    if seg["journal_id"] in posted:
                        continue
                    to_send.append((seg["journal_id"], payload_for(seg, session_id)))

                for chunk in merge_daily_chunks(day_chunks):
                    row_key = f"{path}::{chunk['date']}::{chunk['attribution']}::{chunk['issue_id']}"
                    row_fp = json.dumps(
                        [chunk["tokens"], chunk["requests"], chunk["prompts"], chunk["errors"]],
                        sort_keys=True)
                    if daily_sent.get(row_key) == row_fp:
                        continue  # 自上次成功送出後沒有變化，不必重送
                    daily_items.append({"key": row_key, "fingerprint": row_fp,
                                         "payload": payload_for_daily(chunk, session_id)})
                state["files"][str(path)] = fingerprint

        if correction_stale:
            events, csession_id = parse_creation_events(path)
            correction_tracked[str(path)] = fingerprint
            if events and csession_id:
                batch_todo.append((csession_id, compute_batch_correction(events)))

    # 上次沒送成功的先試，失敗的原因通常是暫時的
    retry = state.get("pending", [])
    queue = [(e["journal_id"], e["payload"]) for e in retry if e["journal_id"] not in posted] + to_send
    daily_items = collapse_daily_items(state.get("daily_pending", []) + daily_items)

    if args.baseline:
        # 「從現在開始」的落實方式：把既有的一律記為已處理，之後只會送新的。
        # 不是刪掉它們，而是標記 —— 刪掉的話，下一次掃描又會把同一批算成
        # 新的，於是永遠補不完也永遠停不下來。
        marked = {jid for jid, _ in queue}
        posted |= marked
        state["posted"] = sorted(posted)
        state["pending"] = []
        for item in daily_items:
            for k in item.get("merged_keys", [item["key"]]):
                daily_sent[k] = item["fingerprint"]
        state["daily_sent"] = daily_sent
        state["daily_pending"] = []
        save_state(state)
        print(f"已將 {len(marked)} 筆既有區間（含每日台帳 {len(daily_items)} 筆）標記為已處理，未送出任何資料")
        print("往後只會送出新產生的用量")
        return {"exit_code": 0, "baseline": True,
                "journal_baselined": len(marked), "daily_baselined": len(daily_items)}

    sent = exists = failed = 0
    write_delivered_tokens = 0  # 驗收第八組：報表要能對得上帳，只算真的送達的
    still_pending: list[dict] = []
    for journal_id, body in queue:
        if args.dry_run:
            if args.verbose:
                total = sum(body["tokens"].values())
                print(f"  [dry-run] journal {journal_id}: {total:,} token, {body['requests']} 請求")
            continue
        try:
            result = post(args.base, key, journal_id, body)
            posted.add(journal_id)
            # exists（409）代表這筆用量本來就已經在伺服器上，不是這次沒送到——
            # 一樣算「送達」，不是「無法處理」。
            write_delivered_tokens += sum(body["tokens"].values())
            if result == "exists":
                exists += 1
            else:
                sent += 1
            if args.verbose:
                print(f"  journal {journal_id}: {result}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            still_pending.append({"journal_id": journal_id, "payload": body})
            if args.verbose:
                print(f"  journal {journal_id}: 失敗 {exc}")

    daily_report = None
    daily_delivered_tokens = 0  # 驗收第八組：只算真的送達的，隔離／待重試的不算
    if args.dry_run:
        if args.verbose:
            for item in daily_items:
                total = sum(item["payload"]["tokens"].values())
                print(f"  [dry-run] 台帳 {item['key']}: {total:,} token，"
                      f"歸屬 {item['payload']['attribution']}，議題 {item['payload']['issue_id']}")
    elif daily_items:
        try:
            sent_items, rejected, result, structural_error = post_daily_resilient(
                args.base, key, daily_items)
        except DailyPostError as exc:
            # 網路或伺服器暫時的問題：還沒送出的（exc.remaining）留到下次重試；
            # 這次迴圈裡已經確定是哪一列資料本身有問題的（exc.rejected）已經
            # 各自記下原因，不放回 pending，否則下次又會把它跟好資料湊成同一批。
            state["daily_pending"] = exc.remaining
            record_rejected_daily_rows(exc.rejected)
            daily_report = f"送出失敗，將於下次執行重試：{exc}"
            if exc.rejected:
                daily_report += f"；另有 {len(exc.rejected)} 筆資料本身不合法已隔離，見 {DAILY_REJECTED_LOG_PATH}"
        else:
            record_rejected_daily_rows(rejected)
            if structural_error is not None:
                # 錯誤訊息認不出是哪一列（整批性的結構錯誤），沒辦法只挑一列
                # 隔離而不誤殺其他列。重送不會變好，不放進 daily_pending 無限
                # 重試——失敗要看得見，但不是看不見的死迴圈。來源資料改變時
                # （檔案內容變了）下次會重新產生並再試。
                state["daily_pending"] = []
                daily_report = f"送出失敗，不會自動重試同一批：{structural_error}"
            else:
                for item in sent_items:
                    for k in item.get("merged_keys", [item["key"]]):
                        daily_sent[k] = item["fingerprint"]
                daily_delivered_tokens = sum(
                    sum(it["payload"]["tokens"].values()) for it in sent_items)
                state["daily_sent"] = daily_sent
                state["daily_pending"] = []
                inserted = result.get("inserted", 0) if result else 0
                updated = result.get("updated", 0) if result else 0
                daily_report = f"新增 {inserted}，更新 {updated}"
            if rejected:
                daily_report += f"；隔離 {len(rejected)} 筆資料本身不合法（見 {DAILY_REJECTED_LOG_PATH}）"

    # 批次校正（#27163）：跟寫入紀錄表／每日台帳不同軌——DELETE＋POST 本身
    # 就是覆蓋式的，沒有「已存在就跳過」的必要，也沒有 pending 重試佇列；
    # 單筆失敗只影響那一張議題，不影響同一批裡的其他張。
    batch_correction = {"sessions": 0, "corrected": 0, "skipped": 0, "failed": 0}
    for csession_id, final in batch_todo:
        if not final:
            continue
        batch_correction["sessions"] += 1
        r = apply_batch_corrections(final, csession_id, args.base, key, args.dry_run, args.verbose)
        for k in ("corrected", "skipped", "failed"):
            batch_correction[k] += r[k]

    state["posted"] = sorted(posted)
    state["pending"] = still_pending
    if not args.dry_run:
        save_state(state)

    attributed = sum(sum(b["tokens"].values()) for _, b in queue)
    daily_total = sum(sum(item["payload"]["tokens"].values()) for item in daily_items)
    print(f"檔案：掃描 {scanned}，未變動略過 {skipped}")
    total = attributed + daily_total
    if total:
        print(f"用量：寫入紀錄表 {attributed:,} token（{100 * attributed / total:.1f}%），"
              f"每日台帳 {daily_total:,}（{100 * daily_total / total:.1f}%）")
    delivered = write_delivered_tokens + daily_delivered_tokens
    unprocessable = total - delivered
    if args.dry_run:
        print(f"待送出：寫入紀錄表 {len(queue)} 筆、每日台帳 {len(daily_items)} 筆"
              "（dry-run，未送出也未寫入狀態）")
    else:
        print(f"寫入紀錄表：送出 {sent}，已存在 {exists}，失敗待重試 {failed}")
        if daily_report:
            print(f"每日台帳：{daily_report}")
        # 驗收第八組：四個數字要能對得上帳——送達的兩邊相加，加上仍然無法
        # 處理的（失敗待重試、已隔離、或整批留待下次），要等於這次處理的總量。
        # 「無法處理」是這次執行結束當下的狀態，不是「永遠救不回來」：待重試
        # 的下次還會再試，只有已隔離的才是真的救不回來（見 daily_usage_rejected.jsonl）。
        print(f"對帳：總量 {total:,}（寫入紀錄表 {write_delivered_tokens:,} ＋ "
              f"每日台帳 {daily_delivered_tokens:,} ＋ 仍無法處理 {unprocessable:,}）")
    if batch_correction["sessions"]:
        print(f"批次校正：{batch_correction['sessions']} 個 session，"
              f"校正 {batch_correction['corrected']}，已存在 {batch_correction['skipped']}，"
              f"失敗 {batch_correction['failed']}"
              + ("（dry-run，未送出）" if args.dry_run else ""))
    return {
        "exit_code": 1 if (failed or batch_correction["failed"]) else 0,
        "scanned": scanned, "skipped": skipped,
        "write_ledger": {"sent": sent, "exists": exists, "failed": failed, "tokens": attributed,
                          "delivered_tokens": write_delivered_tokens},
        "daily_ledger": {"rows": len(daily_items), "tokens": daily_total, "result": daily_report,
                          "delivered_tokens": daily_delivered_tokens},
        "batch_correction": batch_correction,
        "reconcile": {"total": total, "delivered": delivered, "unprocessable": unprocessable},
    }


if __name__ == "__main__":
    sys.exit(main())
