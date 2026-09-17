#!/usr/bin/env python3
"""測試 sync.sh 的 deprecated-registry.json 下架邏輯（Redmine #27129）。

不重寫一份邏輯來測——直接從 sync.sh 抽出內嵌的 python heredoc（只取到 main() 被呼叫之前的
函式定義部分，不觸發任何 Redmine 網路呼叫），在一個假的 $HOME 底下 exec，然後直接呼叫
apply_registry_disable() / fetch_deprecated_registry()。這樣測的是真正會上線的那份程式碼，
不是另一份重寫的模擬。

用法：python3 test_registry_disable.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SYNC_SH = os.path.join(HERE, 'sync.sh')

PASS, FAIL = [], []


def check(label, cond, detail=''):
    if cond:
        PASS.append(label)
    else:
        FAIL.append(f'{label}: {detail}')


def extract_python(sync_sh_path):
    """取出 <<'PY' 與呼叫 main() 之前那一段（只含常數與函式定義，無副作用）。"""
    text = open(sync_sh_path, encoding='utf-8').read()
    start = text.index("<<'PY'\n") + len("<<'PY'\n")
    end_marker = "\ntry:\n    main()\n"
    end = text.index(end_marker, start)
    return text[start:end]


def load_module(home_dir, argv=('--auto',)):
    """在指定的假 $HOME 下 exec 抽出的原始碼，回傳有 apply_registry_disable 等函式的 namespace。"""
    os.environ['HOME'] = home_dir
    src = extract_python(SYNC_SH)
    ns = {'__name__': '__test__'}
    old_argv = sys.argv
    sys.argv = ['sync.sh', *argv]
    try:
        exec(compile(src, SYNC_SH, 'exec'), ns)
    finally:
        sys.argv = old_argv
    return ns


def make_skill(home, name, dev=False):
    d = os.path.join(home, '.claude', 'skills', name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'SKILL.md'), 'w', encoding='utf-8').write('---\nname: x\n---\n版本：v1.0\n')
    if dev:
        open(os.path.join(d, '.nineder-dev'), 'w').close()
    return d


def write_registry(path, entries):
    json.dump(entries, open(path, 'w', encoding='utf-8'), ensure_ascii=False)


def scenario_basic_disable():
    """When1/Then1：#26745 的實測案例——本機已裝，registry 有一筆 Cancelled，下次同步應搬到 disabled/。"""
    home = tempfile.mkdtemp(prefix='nsr-test-')
    try:
        make_skill(home, 'redmine-git-parallel-build')
        ns = load_module(home)
        entries = json.load(open(os.path.join(HERE, 'fixtures', 'deprecated-registry.sample.json'), encoding='utf-8'))
        disabled, malformed, dev_skipped, conflict = ns['apply_registry_disable'](entries, dry=False)
        check('When1/Then1: 回報一筆下架', len(disabled) == 1, disabled)
        if disabled:
            check('When1/Then1: 下架對象是 redmine-git-parallel-build', disabled[0]['name'] == 'redmine-git-parallel-build')
            check('When1/Then1: 附帶 issue_id 26745', disabled[0]['issue'] == 26745)
            check('When1/Then1: moved_to 落在 disabled/ 底下', 'nineder' + os.sep + 'disabled' in disabled[0]['moved_to'])
            check('When1/Then1: moved_to 檔名帶 .disabled-日期', '.disabled-' in os.path.basename(disabled[0]['moved_to']))
            check('When1/Then1: 目的地真的存在', os.path.isdir(disabled[0]['moved_to']))
        check('When1/Then1: 原資料夾已不在 skills/ 底下', not os.path.isdir(os.path.join(home, '.claude', 'skills', 'redmine-git-parallel-build')))
        check('When1/Then1: 沒有誤判成壞資料', len(malformed) == 0, malformed)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def scenario_dev_marker():
    """When2/Then2：.nineder-dev 標記目錄 + 同名出現在 registry → 完全不比對、不搬移。"""
    home = tempfile.mkdtemp(prefix='nsr-test-')
    try:
        make_skill(home, 'some-dev-tool', dev=True)
        ns = load_module(home)
        entries = [{'name': 'some-dev-tool', 'issue_id': 99999, 'status': 'Cancelled', 'deprecated_at': '2026-09-16'}]
        disabled, malformed, dev_skipped, conflict = ns['apply_registry_disable'](entries, dry=False)
        check('When2/Then2: 不下架', len(disabled) == 0, disabled)
        check('When2/Then2: 列進 dev_skipped', len(dev_skipped) == 1 and dev_skipped[0]['name'] == 'some-dev-tool')
        check('When2/Then2: 資料夾維持原狀', os.path.isdir(os.path.join(home, '.claude', 'skills', 'some-dev-tool')))
    finally:
        shutil.rmtree(home, ignore_errors=True)


def scenario_self_protection():
    """安全閥：nineder-skill 自己出現在 registry 也不可自我下架。"""
    home = tempfile.mkdtemp(prefix='nsr-test-')
    try:
        make_skill(home, 'nineder-skill')
        ns = load_module(home)
        entries = [{'name': 'nineder-skill', 'issue_id': 1, 'status': 'Cancelled', 'deprecated_at': '2026-09-16'}]
        disabled, malformed, dev_skipped, conflict = ns['apply_registry_disable'](entries, dry=False)
        check('自我保護: 不下架自己', len(disabled) == 0, disabled)
        check('自我保護: 資料夾還在', os.path.isdir(os.path.join(home, '.claude', 'skills', 'nineder-skill')))
    finally:
        shutil.rmtree(home, ignore_errors=True)


def scenario_not_installed():
    """本機沒裝這支 → 靜默跳過，不報錯、不出現在任何清單。"""
    home = tempfile.mkdtemp(prefix='nsr-test-')
    try:
        ns = load_module(home)
        entries = [{'name': 'never-installed-skill', 'issue_id': 2, 'status': 'Rejected', 'deprecated_at': '2026-09-16'}]
        disabled, malformed, dev_skipped, conflict = ns['apply_registry_disable'](entries, dry=False)
        check('未安裝: 不報錯、不出現在任何清單', not disabled and not malformed and not dev_skipped)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def scenario_malformed_entries():
    """壞資料（非物件／缺 name／name 含路徑字元）要被擋下，不能讓例外往外炸、也不能移動任意路徑。"""
    home = tempfile.mkdtemp(prefix='nsr-test-')
    try:
        make_skill(home, 'redmine-git-parallel-build')
        ns = load_module(home)
        entries = [
            'oops-not-an-object',
            {'issue_id': 3, 'status': 'Cancelled'},                 # 缺 name
            {'name': '../../etc', 'issue_id': 4, 'status': 'Cancelled'},   # 路徑穿越字元
            {'name': 'redmine-git-parallel-build', 'issue_id': 26745, 'status': 'Cancelled', 'deprecated_at': '2026-09-16'},
        ]
        disabled, malformed, dev_skipped, conflict = ns['apply_registry_disable'](entries, dry=False)
        check('壞資料: 三筆都被擋下', len(malformed) == 3, malformed)
        check('壞資料: 正常那筆仍正確下架', len(disabled) == 1 and disabled[0]['name'] == 'redmine-git-parallel-build')
        check('壞資料: /etc 沒有被動到', not os.path.isdir('/etc/.disabled') and os.path.isdir('/etc'))
    finally:
        shutil.rmtree(home, ignore_errors=True)


def scenario_idempotent():
    """When4/Then4：已下架過（本機已是 .disabled-日期 狀態）再跑一次 → 不重複動作、不重複列印。"""
    home = tempfile.mkdtemp(prefix='nsr-test-')
    try:
        make_skill(home, 'redmine-git-parallel-build')
        ns = load_module(home)
        entries = [{'name': 'redmine-git-parallel-build', 'issue_id': 26745, 'status': 'Cancelled', 'deprecated_at': '2026-09-16'}]
        d1, m1, s1, c1 = ns['apply_registry_disable'](entries, dry=False)
        check('第一次: 下架一筆', len(d1) == 1)
        d2, m2, s2, c2 = ns['apply_registry_disable'](entries, dry=False)
        check('When4/Then4: 第二次不重複下架', len(d2) == 0, d2)
        check('When4/Then4: 第二次不產生新的 disabled 目錄', len(d1) == 1)
        disabled_root = os.path.join(home, '.claude', 'nineder', 'disabled')
        entries_on_disk = os.listdir(disabled_root) if os.path.isdir(disabled_root) else []
        check('When4/Then4: disabled/ 底下只有一份', len(entries_on_disk) == 1, entries_on_disk)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def scenario_dry_run():
    """--dry-run：只比對不搬移。"""
    home = tempfile.mkdtemp(prefix='nsr-test-')
    try:
        make_skill(home, 'redmine-git-parallel-build')
        ns = load_module(home)
        entries = [{'name': 'redmine-git-parallel-build', 'issue_id': 26745, 'status': 'Cancelled', 'deprecated_at': '2026-09-16'}]
        disabled, malformed, dev_skipped, conflict = ns['apply_registry_disable'](entries, dry=True)
        check('dry-run: 回報會下架', len(disabled) == 1 and disabled[0]['dry_run'] is True)
        check('dry-run: 資料夾其實沒被搬走', os.path.isdir(os.path.join(home, '.claude', 'skills', 'redmine-git-parallel-build')))
    finally:
        shutil.rmtree(home, ignore_errors=True)


def scenario_fetch_registry():
    """When3/Then3：fetch_deprecated_registry() 對各種壞輸入要 fail-open，回 (None, 原因)，不可拋例外。"""
    home = tempfile.mkdtemp(prefix='nsr-test-')
    try:
        ns = load_module(home)
        fetch = ns['fetch_deprecated_registry']

        good = os.path.join(home, 'good.json')
        write_registry(good, [{'name': 'x', 'issue_id': 1, 'status': 'Cancelled', 'deprecated_at': '2026-09-16'}])
        os.environ['NINEDER_SKILL_DEPRECATED_REGISTRY_FILE'] = good
        entries, err = fetch()
        check('抓取: 合法檔案成功、entries 是 list', err is None and isinstance(entries, list) and len(entries) == 1)

        bad_json = os.path.join(home, 'bad.json')
        open(bad_json, 'w', encoding='utf-8').write('{not valid json,,,')
        os.environ['NINEDER_SKILL_DEPRECATED_REGISTRY_FILE'] = bad_json
        entries, err = fetch()
        check('When3/Then3: 格式不是合法 JSON → 回失敗不拋例外', entries is None and err, err)

        not_array = os.path.join(home, 'not_array.json')
        json.dump({'name': 'x'}, open(not_array, 'w', encoding='utf-8'))
        os.environ['NINEDER_SKILL_DEPRECATED_REGISTRY_FILE'] = not_array
        entries, err = fetch()
        check('When3/Then3: 是合法 JSON 但不是 array → 回失敗', entries is None and err, err)

        os.environ['NINEDER_SKILL_DEPRECATED_REGISTRY_FILE'] = os.path.join(home, 'does-not-exist.json')
        entries, err = fetch()
        check('When3/Then3: 檔案不存在（模擬網路不通／404）→ 回失敗不拋例外', entries is None and err, err)

        os.environ.pop('NINEDER_SKILL_DEPRECATED_REGISTRY_FILE', None)
        os.environ.pop('GITLAB_TOKEN', None)
        entries, err = fetch()
        check('缺 token: 直接回失敗、不嘗試匿名連線', entries is None and 'token' in err, err)
        # 不測「有 token」這條路——那會真的打一次 gitlab.nineder.com，不做這種會打到真實外部服務的測試。
        # 有 token 之後走的就是標準 urllib 呼叫，行為由 fetch_deprecated_registry 的例外處理統一接住。
    finally:
        os.environ.pop('NINEDER_SKILL_DEPRECATED_REGISTRY_FILE', None)
        os.environ.pop('GITLAB_TOKEN', None)
        shutil.rmtree(home, ignore_errors=True)


def scenario_name_reuse_conflict():
    """名字重複使用防護：舊票 Cancelled 留在 registry 裡，但同名新票現在是 Resolved
    （resolved_names 有這個名字）→ 不下架，記進 conflict，不當成安全閥（不進 dev_skipped）。"""
    home = tempfile.mkdtemp(prefix='nsr-test-')
    try:
        make_skill(home, 'redmine-git-parallel-build')
        ns = load_module(home)
        entries = [{'name': 'redmine-git-parallel-build', 'issue_id': 26745, 'status': 'Cancelled',
                    'deprecated_at': '2026-09-16'}]

        # 沒有名字重複使用時（resolved_names 是空集合），行為跟之前一樣：正常下架
        disabled, malformed, dev_skipped, conflict = ns['apply_registry_disable'](entries, dry=False)
        check('無衝突時: 正常下架', len(disabled) == 1 and len(conflict) == 0)

        # 重裝一次，這次名字現在有一張 Resolved 票在用
        make_skill(home, 'redmine-git-parallel-build')
        disabled2, malformed2, dev_skipped2, conflict2 = ns['apply_registry_disable'](
            entries, dry=False, resolved_names={'redmine-git-parallel-build'})
        check('名字重複使用: 不下架', len(disabled2) == 0, disabled2)
        check('名字重複使用: 記進 conflict', len(conflict2) == 1 and conflict2[0]['name'] == 'redmine-git-parallel-build', conflict2)
        check('名字重複使用: 資料夾維持原狀', os.path.isdir(os.path.join(home, '.claude', 'skills', 'redmine-git-parallel-build')))
        check('名字重複使用: 不算進 dev_skipped（那是給 .nineder-dev 用的）', len(dev_skipped2) == 0)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def scenario_real_format_fixture():
    """實際上線的 deprecated-registry.json 除了 name/issue_id/status/deprecated_at 四欄，
    #27128 那邊實際多帶了 version/reason 兩欄——確認多餘欄位不影響比對/下架邏輯。"""
    home = tempfile.mkdtemp(prefix='nsr-test-')
    try:
        make_skill(home, 'redmine-git-parallel-build')
        ns = load_module(home)
        entries = [{
            'name': 'redmine-git-parallel-build', 'issue_id': 26745, 'status': 'Cancelled',
            'deprecated_at': '2026-09-16', 'version': 'v7.1', 'reason': '未附原因',
        }]
        disabled, malformed, dev_skipped, conflict = ns['apply_registry_disable'](entries, dry=False)
        check('多餘欄位不影響下架', len(disabled) == 1 and disabled[0]['name'] == 'redmine-git-parallel-build', disabled)
        check('多餘欄位不會被誤判成壞資料', len(malformed) == 0, malformed)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main():
    for fn in [scenario_basic_disable, scenario_dev_marker, scenario_self_protection, scenario_not_installed,
               scenario_malformed_entries, scenario_idempotent, scenario_dry_run, scenario_fetch_registry,
               scenario_name_reuse_conflict, scenario_real_format_fixture]:
        fn()

    print(f'PASS {len(PASS)} / FAIL {len(FAIL)}')
    for f in FAIL:
        print('  FAIL:', f)
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
