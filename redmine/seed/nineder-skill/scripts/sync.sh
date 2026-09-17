#!/usr/bin/env bash
# nineder-skill / scripts/sync.sh —— 公司 Skill 單一來源同步器
# 規格正本：Redmine #26915（v1.0）；分發模型：Redmine #26309【分發模型 v2】
#
# 用法：
#   sync.sh --auto            SessionStart hook 用：靜默；缺鑰匙／斷網 exit 0；有變動才印一行
#   sync.sh --sync            cron 用：同 --auto
#   sync.sh --report          互動用：印 JSON 給 /nineder-skill 渲染成健檢報告（不寫檔）
#   sync.sh --install <票號>  安裝／更新任一專案的一支 Resolved Skill（其他專案的一列一支指令就是它）
#   任何模式可加 --dry-run    只比對不寫任何檔
#
# 設計要點（全部有票面依據，改之前先讀 #26915）：
#   * 鑰匙：環境變數 REDMINE_API_KEY → 鑰匙檔 ~/.claude/nineder/redmine_api_key → 都沒有＝缺鑰匙
#   * 自動範圍：只有 AUTO_PROJECT_IDS（47 耐德集團工作區）的 Resolved 自動裝／更新／下架
#   * 砍光同名：先下載並驗證通過，才整目錄刪除 ~/.claude/skills/<名稱>/ 再解開；驗證失敗一個位元組都不動
#   * 不砍：名稱不在 47 集合裡的目錄、plugin cache、目前 project 的 .claude/skills（同名影子只警告）
#   * 下架：47 的票變成 Cancelled／Rejected → 搬到 ~/.claude/nineder/disabled/<名稱>.disabled-<日期>（不留在 skills/ 底下，
#     因為留在那裡 Claude Code 會把它當成另一支 skill 載入）
#   * 下架來源二（#27129）：額外讀取 GitLab repo nineder/claude/skills 根目錄的 deprecated-registry.json
#     （由 #27128 的 plugin 在任一 Skill 票轉 Cancelled／Rejected 時維護），name 欄位比對本機
#     ~/.claude/skills/*/ 資料夾名稱——涵蓋全部 8 個 Skill tracker 專案，不看安裝來源（47 自動裝／
#     --install 票號／手動複製一視同仁）；沿用同一套下架與安全閥邏輯，不擴大自動安裝範圍。
#     抓取失敗（網路不通、GitLab 401/404、格式不是合法 JSON）＝本次同步跳過下架偵測，不影響
#     其他既有流程，比照缺鑰匙的 fail-open 處理。認證方式與快取策略待 #27128 完成、兩個開放問題
#     定案後再調整——目前是先試不帶 token 的請求，失敗就整段跳過。
#   * 審查中不下架（#26915 驗收 15）：票從 Resolved 退回 In Progress 等非終結狀態時，本機不裝、不更新、不下架，
#     維持上一個 Resolved 版本並印一行提示 —— 升版送審期間全員不該失去這支 skill
#   * 開發保護：目錄裡有 .nineder-dev 標記檔 → 本腳本完全不碰該目錄，只在報告標「開發中」
#   * 自我更新：本腳本自己也在 47 集合裡；整支邏輯包在 main() 裡，bash 會先讀完整個函式再執行，
#     所以刪掉自己所在的目錄不影響這一次執行
#   * fail-open：--auto／--sync 任何錯誤都 exit 0，不阻擋對話開始
set -u

main() {
  local mode="${1:---auto}"
  command -v python3 >/dev/null 2>&1 || { [ "$mode" = "--report" ] && echo '{"error":"python3 not found"}'; return 0; }
  python3 - "$@" <<'PY'
import datetime, glob, io, json, os, re, shutil, sys, tarfile, tempfile, time, urllib.error, urllib.request

BASE = 'https://redmine.nineder.com'
AUTO_PROJECT_IDS = {47}                 # 耐德集團工作區。要開放第二個專案改這裡（並改 #26915）
SKILL_TRACKER_ID = 13
RESOLVED = 'Resolved'
DISABLE_STATUSES = {'Cancelled', 'Rejected'}   # 只有這兩個狀態才下架；其餘非 Resolved 一律保留舊版（#26915 驗收 5 與 15）
HOME = os.path.expanduser('~')
SKILLS = os.path.join(HOME, '.claude', 'skills')
STATE = os.path.join(HOME, '.claude', 'nineder')
KEY_FILE = os.path.join(STATE, 'redmine_api_key')
LAST = os.path.join(STATE, 'last_sync.json')
DISABLED = os.path.join(STATE, 'disabled')
LOCK = os.path.join(STATE, '.sync.lock')
WIKI = BASE + '/projects/47/wiki/Claude_Code_%E6%96%B0%E6%A9%9F%E5%99%A8%E5%AE%89%E8%A3%9D'
SELF = 'nineder-skill'

# ---- deprecated-registry.json（#27129）----
GITLAB_BASE = 'https://gitlab.nineder.com'
SKILLS_REPO = 'nineder/claude/skills'          # #27128 維護，格式由該票定案
SKILLS_REPO_BRANCH = 'main'
REGISTRY_FILE_PATH = 'deprecated-registry.json'
GITLAB_TOKEN_FILE = os.path.join(STATE, 'gitlab_token')
NAME_RE = re.compile(r'^[A-Za-z0-9._-]+$')     # 防禦：registry 的 name 若含路徑字元一律當成壞資料跳過

args = sys.argv[1:]
mode = next((a for a in args if a in ('--auto', '--sync', '--report', '--install')), '--auto')
dry = '--dry-run' in args
report = mode == '--report'
dry = dry or report                     # --report 一律唯讀：不裝、不搬、不寫 last_sync
install_id = None
if mode == '--install':
    try: install_id = int(args[args.index('--install') + 1])
    except Exception: print('用法：sync.sh --install <票號>'); sys.exit(0)

out_lines = []
def say(s):
    out_lines.append(s)

# ---------- 鑰匙 ----------
def load_key():
    k = os.environ.get('REDMINE_API_KEY', '').strip()
    if k: return k, 'env'
    try:
        k = open(KEY_FILE, encoding='utf-8').read().strip()
        if k: return k, 'file'
    except OSError: pass
    return None, None

def http(path, key, timeout=5, binary=False):
    req = urllib.request.Request(BASE + path, headers={'X-Redmine-API-Key': key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else json.loads(data)

def paged(path, key):
    items, offset = [], 0
    while True:
        d = http(f'{path}&offset={offset}&limit=100', key)
        items += d.get('issues', [])
        if len(items) >= d.get('total_count', 0) or not d.get('issues'): break
        offset += 100
    return items

# ---------- deprecated-registry.json（#27129）----------
def load_gitlab_token():
    t = os.environ.get('GITLAB_TOKEN', '').strip()
    if t: return t
    try:
        t = open(GITLAB_TOKEN_FILE, encoding='utf-8').read().strip()
        return t or None
    except OSError:
        return None

def fetch_deprecated_registry():
    """回 (entries, None) 或 (None, 失敗原因字串)；entries 是 list[dict]。
    測試用逃生門：設定 NINEDER_SKILL_DEPRECATED_REGISTRY_FILE 指向本機檔案，改讀那份檔案而不打網路。
    正式路徑打 GitLab Files API；認證與快取策略待 #27128 完成、兩個開放問題定案後再調整——
    現在是先試不帶 token（有設定就帶），任何失敗（網路、401/403/404、内容不是合法 JSON array）
    一律回傳失敗原因，呼叫端要整段跳過下架偵測，不可讓例外往外炸。"""
    override = os.environ.get('NINEDER_SKILL_DEPRECATED_REGISTRY_FILE', '').strip()
    try:
        if override:
            raw = open(override, encoding='utf-8').read()
        else:
            import urllib.parse
            proj = urllib.parse.quote(SKILLS_REPO, safe='')
            fp = urllib.parse.quote(REGISTRY_FILE_PATH, safe='')
            url = f'{GITLAB_BASE}/api/v4/projects/{proj}/repository/files/{fp}/raw?ref={SKILLS_REPO_BRANCH}'
            headers = {}
            tok = load_gitlab_token()
            if tok: headers['PRIVATE-TOKEN'] = tok
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
                raw = r.read().decode('utf-8', errors='replace')
        entries = json.loads(raw)
        if not isinstance(entries, list): raise ValueError('registry 內容不是 JSON array')
        return entries, None
    except Exception as e:
        return None, f'{e.__class__.__name__}: {e}'

def apply_registry_disable(entries, dry):
    """套用 deprecated-registry.json 的下架邏輯；抽成獨立函式方便測試（#27129，見同目錄 test_registry_disable.py）。
    回 (disabled, malformed, dev_skipped) 三個 list，呼叫端自行併回 result。
    比對依 name 對本機資料夾名稱，不看安裝來源；已下架過的（資料夾已不在 SKILLS 底下）自然被
    isdir 擋掉，不會重複動作；.nineder-dev 與自我保護兩個安全閥與 47 下架共用同一套語意。"""
    disabled, malformed, dev_skipped = [], [], []
    for entry in entries:
        if not isinstance(entry, dict):
            malformed.append({'entry': entry, 'reason': '不是物件'}); continue
        name = (entry.get('name') or '').strip()
        if not name or not NAME_RE.match(name):
            malformed.append({'entry': entry, 'reason': 'name 缺漏或含不安全字元'}); continue
        if name == SELF:
            continue                                        # 安全閥：同步器不自我下架
        src = os.path.join(SKILLS, name)
        if not os.path.isdir(src): continue                 # 本機沒裝，或先前已下架過（不重複動作）
        if os.path.exists(os.path.join(src, '.nineder-dev')):
            dev_skipped.append({'name': name, 'issue': entry.get('issue_id'), 'source': 'registry'}); continue
        dst = os.path.join(DISABLED, f'{name}.disabled-{datetime.date.today():%Y%m%d}')
        if not dry:
            os.makedirs(DISABLED, exist_ok=True)
            if os.path.exists(dst): dst += datetime.datetime.now().strftime('-%H%M%S')
            shutil.move(src, dst)
        disabled.append({'name': name, 'issue': entry.get('issue_id'), 'status': entry.get('status'),
                          'deprecated_at': entry.get('deprecated_at'), 'moved_to': dst, 'dry_run': dry})
    return disabled, malformed, dev_skipped

# ---------- 版本 ----------
VER_RE = re.compile(r'版本[：:]\s*v?(\d+(?:\.\d+)*)')
def vt(v):
    if not v: return None
    m = re.search(r'(\d+(?:\.\d+)*)', v)
    return tuple(int(x) for x in m.group(1).split('.')) if m else None
def vs(t): return 'v' + '.'.join(map(str, t)) if t else None

def version_line_of(text):
    """frontmatter 之後第一個非空行；回 (版本tuple, 第一行是否 ---)"""
    lines = text.split('\n')
    if not lines or lines[0].strip() != '---': return None, False
    try: end = lines.index('---', 1)
    except ValueError: return None, True
    for l in lines[end + 1:]:
        if l.strip():
            m = VER_RE.search(l); return (vt(m.group(1)) if m else None), True
    return None, True

def local_skills():
    res = {}
    if not os.path.isdir(SKILLS): return res
    for name in sorted(os.listdir(SKILLS)):
        p = os.path.join(SKILLS, name, 'SKILL.md')
        if not os.path.isfile(p): continue
        try: v, _ = version_line_of(open(p, encoding='utf-8', errors='replace').read())
        except OSError: v = None
        res[name] = {'version': v, 'dev': os.path.exists(os.path.join(SKILLS, name, '.nineder-dev'))}
    return res

# ---------- 安裝（先驗再砍再解） ----------
def cf(issue, cid):
    for c in issue.get('custom_fields', []):
        if c.get('id') == cid: return (c.get('value') or '').strip()
    return ''

def fetch_and_verify(issue_id, name, ver, key):
    """回 (tmpdir_with_SKILL.md, note) 或 (None, 失敗原因)。tmpdir 內就是要搬進 skills/<name>/ 的完整內容。"""
    d = http(f'/issues/{issue_id}.json?include=attachments', key, timeout=15)['issue']
    want_tgz, want_md = f'SKILL-{ver}.tar.gz', f'SKILL-{ver}.md'
    atts = {a['filename']: a for a in d.get('attachments', [])}
    a = atts.get(want_tgz) or atts.get(want_md)
    if not a: return None, f'漂移：票頭 {ver} 找不到 {want_tgz} 或 {want_md}'
    url = a['content_url'].replace('http://', 'https://')
    blob = http(url[len(BASE):] if url.startswith(BASE) else url, key, timeout=30, binary=True) if url.startswith(BASE) else None
    if blob is None:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'X-Redmine-API-Key': key}), timeout=30) as r: blob = r.read()
    tmp = tempfile.mkdtemp(prefix='nineder-skill-')
    try:
        if a['filename'].endswith('.tar.gz'):
            with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tf:
                members = tf.getmembers()
                for m in members:
                    n = m.name
                    if n.startswith('/') or '..' in n.split('/') or m.issym() or m.islnk():
                        raise ValueError(f'tar 內含不安全路徑：{n}')
                try: tf.extractall(tmp, filter='data')
                except TypeError: tf.extractall(tmp)
            # 允許「多包一層」：唯一子目錄裡有 SKILL.md 就往下走一層
            if not os.path.isfile(os.path.join(tmp, 'SKILL.md')):
                subs = [x for x in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, x)) and not x.startswith('.')]
                if len(subs) == 1 and os.path.isfile(os.path.join(tmp, subs[0], 'SKILL.md')):
                    inner = os.path.join(tmp, subs[0]); tmp2 = tempfile.mkdtemp(prefix='nineder-skill-')
                    shutil.rmtree(tmp2); shutil.move(inner, tmp2); shutil.rmtree(tmp); tmp = tmp2
        else:
            open(os.path.join(tmp, 'SKILL.md'), 'wb').write(blob)
        p = os.path.join(tmp, 'SKILL.md')
        if not os.path.isfile(p): raise ValueError('解開後頂層沒有 SKILL.md')
        text = open(p, encoding='utf-8', errors='replace').read()
        fv, fm = version_line_of(text)
        if not fm: raise ValueError('內容不是 SKILL 檔（首行不是 frontmatter；未授權時 Redmine 回 200 加登入頁）')
        if fv != vt(ver): raise ValueError(f'漂移：檔內版本 {vs(fv)} ≠ 票頭 {ver}')
        # 清掉 macOS 打包垃圾
        for root, dirs, files in os.walk(tmp):
            for f in files:
                if f.startswith('._') or f == '.DS_Store': os.remove(os.path.join(root, f))
        return tmp, a['filename']
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True); return None, str(e)

def place(tmp, name):
    target = os.path.join(SKILLS, name)
    os.makedirs(SKILLS, exist_ok=True)
    if os.path.isdir(target): shutil.rmtree(target)          # 砍光同名：只有 ~/.claude/skills/<name>/，且已驗證通過
    shutil.move(tmp, target)
    for root, dirs, files in os.walk(target):
        for f in files:
            if root.endswith('/scripts') and f.endswith('.sh'):
                os.chmod(os.path.join(root, f), 0o755)

# ---------- 主流程 ----------
def main():
    os.makedirs(STATE, exist_ok=True)
    key, ksrc = load_key()
    result = {'mode': mode, 'dry_run': dry, 'key': {'source': ksrc, 'valid': None}, 'wiki': WIKI,
              'mcp': {}, 'auto_project_ids': sorted(AUTO_PROJECT_IDS), 'auto': [], 'installed': [], 'updated': [], 'disabled': [],
              'dev_skipped': [], 'ahead': [], 'failed': [], 'others': [], 'shadows': [], 'set47': [], 'local_other': [], 'reviewing': [],
              'registry': {'ok': None, 'error': None, 'entries': 0}, 'registry_disabled': [], 'registry_malformed': [],
              'last_sync': None, 'error': None}
    # MCP 註冊狀態（只看檔案，不碰 MCP）
    try:
        cj = json.load(open(os.path.join(HOME, '.claude.json')))
        servers = set((cj.get('mcpServers') or {}).keys())
        result['mcp'] = {'nineder-redmine': 'nineder-redmine' in servers, 'nineder-google': 'nineder-google' in servers}
    except Exception:
        result['mcp'] = {'nineder-redmine': None, 'nineder-google': None}
    try: result['last_sync'] = json.load(open(LAST))
    except Exception: pass

    if not key:
        if report: result['key']['valid'] = False; print(json.dumps(result, ensure_ascii=False)); return
        if mode == '--install': print('缺 Redmine API key：請先輸入 /nineder-skill 完成設定'); return
        say(f'nineder-skill：尚未設定 Redmine API key，請新開對話後輸入 /nineder-skill 完成設定（手冊：{WIKI}）')
        return

    # 鎖（同時開兩個 session）
    if not report:
        try:
            if os.path.isdir(LOCK) and time.time() - os.path.getmtime(LOCK) > 600: shutil.rmtree(LOCK, ignore_errors=True)
            os.mkdir(LOCK)
        except FileExistsError:
            return
    try:
        try:
            resolved = paged(f'/issues.json?tracker_id={SKILL_TRACKER_ID}&status_id=3', key)      # 3 = Resolved
            set47 = []
            for pid in AUTO_PROJECT_IDS:
                set47 += paged(f'/issues.json?project_id={pid}&tracker_id={SKILL_TRACKER_ID}&status_id=*', key)
            result['key']['valid'] = True
        except urllib.error.HTTPError as e:
            result['key']['valid'] = False if e.code in (401, 403) else None
            result['error'] = f'HTTP {e.code}'
            if report: print(json.dumps(result, ensure_ascii=False))
            elif mode == '--install': print(f'Redmine 回 HTTP {e.code}：API key 無效或無權限')
            return
        except Exception as e:
            result['error'] = f'網路：{e.__class__.__name__}'
            if report: print(json.dumps(result, ensure_ascii=False))
            elif mode == '--install': print(f'連不上 Redmine：{e}')
            return

        local = local_skills()
        names47 = {}
        for i in set47:
            n = cf(i, 27)
            if n: names47[n] = i
        result['set47'] = sorted(names47)

        # ---- --install <票號>：任一專案的 Resolved 一支 ----
        if mode == '--install':
            i = next((x for x in resolved if x['id'] == install_id), None)
            if not i:
                print(f'#{install_id} 不是 Resolved 的 Skill 票（或你無權看到）'); return
            n, v = cf(i, 27), cf(i, 28)
            if not n or not v: print(f'#{install_id} 票頭缺 Skill 名稱或現行版本'); return
            if local.get(n, {}).get('dev'): print(f'{n}：有 .nineder-dev 標記，開發中，不動'); return
            if dry: print(f'[dry-run] 會安裝 {n} {v}'); return
            tmp, note = fetch_and_verify(i['id'], n, v, key)
            if not tmp: print(f'{n} 安裝失敗：{note}'); return
            place(tmp, n); print(f'{n} {v} 安裝完成（#{i["id"]}，{note}）；新開對話生效')
            return

        # ---- 47 自動 ----
        for i in resolved:
            n, v = cf(i, 27), cf(i, 28)
            pid = i.get('project', {}).get('id')
            entry = {'issue': i['id'], 'name': n, 'remote': v, 'project': i.get('project', {}).get('name'),
                     'local': vs(local.get(n, {}).get('version')) if n in local else None}
            if pid not in AUTO_PROJECT_IDS:
                if not n or not v: continue
                lv = local.get(n, {}).get('version')
                if n not in local: entry['state'] = 'missing'
                elif lv is None or lv < vt(v): entry['state'] = 'outdated'
                else: entry['state'] = 'ok'
                entry['install_cmd'] = f'~/.claude/skills/{SELF}/scripts/sync.sh --install {i["id"]}'
                result['others'].append(entry); continue
            result['auto'].append(entry)
            if not n: entry['state'] = 'failed'; result['failed'].append({**entry, 'reason': 'cf27 空'}); continue
            if not v: entry['state'] = 'failed'; result['failed'].append({**entry, 'reason': '尚無可安裝版本（cf28 空）'}); continue
            if local.get(n, {}).get('dev'): entry['state'] = 'dev'; result['dev_skipped'].append(entry); continue
            lv = local.get(n, {}).get('version') if n in local else None
            if n in local and lv is not None and lv > vt(v):
                entry['state'] = 'ahead'; result['ahead'].append(entry); continue
            if n in local and lv == vt(v):
                entry['state'] = 'ok'; continue
            entry['state'] = 'install' if n not in local else 'update'
            if dry:
                (result['installed'] if n not in local else result['updated']).append({**entry, 'dry_run': True}); continue
            tmp, note = fetch_and_verify(i['id'], n, v, key)
            if not tmp: entry['state'] = 'failed'; result['failed'].append({**entry, 'reason': note}); continue
            place(tmp, n)
            entry['state'] = 'installed' if n not in local else 'updated'
            (result['installed'] if n not in local else result['updated']).append({**entry, 'file': note})

        # ---- 47 下架：本機有、票已 Cancelled／Rejected；其餘非 Resolved 只提示不動 ----
        for n, i in names47.items():
            if i['status']['name'] == RESOLVED or n not in local: continue
            if n == SELF:
                # 同步器不自我下架：搬走自己會讓這台機器失去同步能力，且要等 plugin bootstrap 重種才回得來
                result['failed'].append({'issue': i['id'], 'name': n, 'state': 'self_not_resolved',
                                         'reason': f'本 skill 的票 #{i["id"]} 現為 {i["status"]["name"]}，尚未核可；已安裝的版本保留不下架'})
                continue
            if local[n]['dev']: result['dev_skipped'].append({'issue': i['id'], 'name': n, 'status': i['status']['name']}); continue
            if i['status']['name'] not in DISABLE_STATUSES:
                # 審查中／暫緩：保留上一個 Resolved 版本，一個位元組都不動（#26915 驗收 15）
                result['reviewing'].append({'issue': i['id'], 'name': n, 'status': i['status']['name'],
                                            'local': vs(local[n]['version'])})
                continue
            src = os.path.join(SKILLS, n)
            dst = os.path.join(DISABLED, f'{n}.disabled-{datetime.date.today():%Y%m%d}')
            if not dry:
                os.makedirs(DISABLED, exist_ok=True)
                if os.path.exists(dst): dst += datetime.datetime.now().strftime('-%H%M%S')
                shutil.move(src, dst)
            result['disabled'].append({'issue': i['id'], 'name': n, 'status': i['status']['name'], 'moved_to': dst, 'dry_run': dry})

        # ---- registry 下架：跨全部 8 個 Skill tracker 專案，不限 47，不看安裝來源（#27129）----
        registry_entries, registry_err = fetch_deprecated_registry()
        result['registry'] = {'ok': registry_err is None, 'error': registry_err,
                               'entries': len(registry_entries) if registry_entries else 0}
        if registry_entries is not None:
            reg_disabled, reg_malformed, reg_dev_skipped = apply_registry_disable(registry_entries, dry)
            result['registry_disabled'] = reg_disabled
            result['registry_malformed'] = reg_malformed
            result['dev_skipped'] += reg_dev_skipped

        # ---- 同名影子 ----
        installed_ver = {}
        try:
            ip = json.load(open(os.path.join(HOME, '.claude', 'plugins', 'installed_plugins.json')))
            for k, v in (ip.get('plugins') or ip).items():
                if isinstance(v, dict) and v.get('version'): installed_ver[k] = v['version']
        except Exception: pass
        for n in names47:
            seen = {}
            for p in glob.glob(os.path.join(HOME, '.claude', 'plugins', 'cache', '*', '*', '*', 'skills', n)):
                parts = p.split(os.sep); mk, plug, ver = parts[-5], parts[-4], parts[-3]
                cur = installed_ver.get(f'{plug}@{mk}')
                if cur and ver != cur: continue                       # 只報目前安裝版
                if not cur and (f'{mk}/{plug}' in seen) and vt(ver) <= vt(seen[f'{mk}/{plug}'][0]): continue
                seen[f'{mk}/{plug}'] = (ver, p)
            for ver, p in seen.values():
                result['shadows'].append({'name': n, 'path': p, 'kind': 'plugin cache'})
            cwd = os.getcwd()
            if os.path.realpath(cwd) != os.path.realpath(HOME):
                p = os.path.join(cwd, '.claude', 'skills', n)
                if os.path.isdir(p): result['shadows'].append({'name': n, 'path': p, 'kind': 'project'})

        # ---- 本機非 47 集合的目錄（只列不動）----
        result['local_other'] = sorted(n for n in local if n not in names47)

        if not dry and not report:
            json.dump({'at': datetime.datetime.now().isoformat(timespec='seconds'), 'mode': mode,
                       'installed': [x['name'] for x in result['installed']], 'updated': [x['name'] for x in result['updated']],
                       'disabled': [x['name'] for x in result['disabled']], 'failed': [x['name'] for x in result['failed']]},
                      open(LAST, 'w'), ensure_ascii=False)

        if report:
            print(json.dumps(result, ensure_ascii=False, indent=1)); return

        # ---- --auto／--sync 的一行輸出 ----
        parts = []
        if result['installed']: parts.append('已安裝 ' + '、'.join(f'{x["name"]} {x["remote"]}' for x in result['installed']))
        if result['updated']: parts.append('已更新 ' + '、'.join(f'{x["name"]} {x["local"]}→{x["remote"]}' for x in result['updated']))
        if parts: say('nineder-skill：' + ('[dry-run] ' if dry else '') + '；'.join(parts) + '（新開對話生效）')
        for x in result['reviewing']:
            say(f'nineder-skill：{x["name"]} 審查中（票 #{x["issue"]} 現為 {x["status"]}），本機維持 {x["local"]} 不動')
        for x in result['disabled']:
            say(f'nineder-skill：已停用 {x["name"]}（#{x["issue"]} 現為 {x["status"]}，已搬到 {x["moved_to"]}）')
        for x in result['registry_disabled']:
            say(f'nineder-skill：{x["name"]} 已停用（見 registry）')
        for x in result['failed']:
            n = x['name'] or '#' + str(x['issue'])
            if x.get('state') == 'self_not_resolved':
                say(f'nineder-skill：{x["reason"]}')          # 已安裝且刻意保留，不能說成「未安裝」
            else:
                say(f'nineder-skill：{n} 未安裝——{x["reason"]}')
        if result['shadows']:
            kinds = sorted({x['kind'] for x in result['shadows']}); names = sorted({x['name'] for x in result['shadows']})
            say(f'nineder-skill：同名影子 {len(result["shadows"])} 處（{"、".join(kinds)}）：{"、".join(names)}——會與 ~/.claude/skills/ 的版本並存、破壞一致性；輸入 /nineder-skill 看完整路徑，本腳本不代刪')
        pend = [x for x in result['others'] if x['state'] != 'ok']
        if pend: say(f'nineder-skill：其他專案有 {len(pend)} 支可裝／可更新，輸入 /nineder-skill 看清單')
    finally:
        if not report: shutil.rmtree(LOCK, ignore_errors=True)

try:
    main()
except Exception as e:
    if report: print(json.dumps({'error': f'{e.__class__.__name__}: {e}'}, ensure_ascii=False))
    # --auto／--sync：fail-open，什麼都不印
for l in out_lines: print(l)
PY
  return 0
}

main "$@"
exit 0
