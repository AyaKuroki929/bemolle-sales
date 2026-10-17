#!/usr/bin/env python3
"""今月が誕生日のお客様を、売上日報のスプレッドシート「誕生日」シートに書き出す。
毎月1日に GitHub Actions（birthdays.yml）が動かす。売上日報の画面「誕生日」タブがこのシートを読む。

  python3 fetch_birthdays.py [2026-11] [--dry] [--skip-if-done]
  --skip-if-done … その月がもう作られていれば何もしない（1日の1時・4時・7時に起動し、9時には必ずできている形）

決まりごと（2026-10-13 彩さん）
  ・誕生日はうらかたさんの顧客管理から取る
  ・スタッフは外す（顧客管理のメモに「スタッフ」とある人／売上日報のスタッフ一覧にいる人）
  ・直近1年に「コースの記録がある」か「商品を別々の日に2回以上買った（定期便を含む）」人だけ残す
    ＝体験・サービスメニューだけの人、商品を1回買っただけの人、1年以上来ていない人が外れる（2026-10-13 彩さん）

⚠️ このリポジトリは公開。ログにお客様の名前・誕生日を出さない（件数だけ出す）。
"""
import os, sys, re, time, datetime, unicodedata

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
DRY = '--dry' in sys.argv
SKIP_IF_DONE = '--skip-if-done' in sys.argv   # 下で sys.argv を書き換える前に読んでおく
JST = datetime.timezone(datetime.timedelta(hours=9))
TARGET = ARGS[0] if ARGS else datetime.datetime.now(JST).strftime('%Y-%m')
if not re.fullmatch(r'\d{4}-\d{2}', TARGET):
    sys.exit(f'月の形が違います: {TARGET}（例 2026-11）')
sys.argv = [sys.argv[0], TARGET, 'out']          # fetch_urakata は読み込み時に引数を見る
import fetch_urakata as fu
import import_sales as isl

SHEET = '誕生日'
LOG_SHEET = '誕生日_作成記録'          # 対象月・作成日時・人数（0人の月も「作った」と分かるように）
HEAD = ['対象月', 'お客様', '誕生日', '最後の来店日', '作成日時']


def norm(name):
    return re.sub(r'[\s　]+', '', unicodedata.normalize('NFKC', str(name)))


def months_back(target, n):
    """target を含めて n か月さかのぼった年月の一覧（古い順）"""
    y, m = map(int, target.split('-'))
    out = []
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def read_month(page, y, m):
    """その月の売上（物販・サービス・コース）を (区分, 日付, 名称, 顧客) で返す
    2026-10-18 新システム向け：fetch_urakata.fetch_month が画面の裏のデータを読む"""
    rows, _ = fu.fetch_month(page, y, m)
    return [(r['区分'], r['日付'], r['名称'], r['顧客']) for r in rows]


def read_customers(page):
    """顧客管理の全員を {名前, 誕生日, メモ} で返す
    2026-10-18 新システム向け：/dashboard/customers は20人ずつのページ送り。pagination.pages ぶん回す"""
    out, seen = [], set()
    page_no, pages = 1, 1
    while page_no <= pages:
        data = fu.loader_data(page, f'/dashboard/customers?page={page_no}', 'routes/dashboard/customers')
        pg = data.get('pagination') or {}
        pages = int(pg.get('pages') or 1)
        for c in data.get('customers') or []:
            cid = c.get('id') or c.get('name')
            if cid in seen:
                continue
            seen.add(cid)
            bd = str(c.get('birthday') or '')
            m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', bd)
            out.append({'名前': str(c.get('name') or '').strip(),
                        '誕生日': m.groups() if m else None,
                        'メモ': str(c.get('memo') or '')})
        page_no += 1
    if not out:
        sys.exit('顧客一覧が見つかりませんでした')
    return out


def staff_names(ssid, at):
    try:
        return {norm(r[0]) for r in isl.read(ssid, at, 'スタッフ') if r and str(r[0]).strip()}
    except Exception as e:
        print(f'⚠️ スタッフ一覧が読めませんでした（{e}）。顧客管理のメモだけで外します')
        return set()


def write_sheet(ssid, at, rows):
    base = f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}'
    meta = isl.api(base + '?fields=sheets.properties.title', at)
    if SHEET not in [s['properties']['title'] for s in meta['sheets']]:
        isl.api(base + ':batchUpdate', at, 'POST',
                {'requests': [{'addSheet': {'properties': {'title': SHEET}}}]})
    old = isl.read(ssid, at, SHEET)
    keep = [isl.pad(r, len(HEAD)) for r in old if r and r[0] != TARGET]   # 他の月は残す
    allrows = [HEAD] + keep + rows
    rng = isl.urllib.parse.quote(f"'{SHEET}'!A1:Z")
    isl.api(f'{base}/values/{rng}:clear', at, 'POST', {})
    isl.api(f"{base}/values/{isl.urllib.parse.quote(f'{SHEET}!A1')}?valueInputOption=RAW", at, 'PUT',
            {'values': allrows})
    back = [r for r in isl.read(ssid, at, SHEET) if r and r[0] == TARGET]
    if len(back) != len(rows):
        sys.exit(f'書き込んだ{len(rows)}件と読み戻した{len(back)}件が合いません')
    return len(back)


def done_months(ssid, at):
    try:
        return {r[0] for r in isl.read(ssid, at, LOG_SHEET) if r}
    except Exception:
        return set()                             # シートがまだ無い＝どの月も作っていない


def record_done(ssid, at, n):
    base = f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}'
    meta = isl.api(base + '?fields=sheets.properties.title', at)
    if LOG_SHEET not in [s['properties']['title'] for s in meta['sheets']]:
        isl.api(base + ':batchUpdate', at, 'POST',
                {'requests': [{'addSheet': {'properties': {'title': LOG_SHEET}}}]})
    rows = [isl.pad(r, 3) for r in isl.read(ssid, at, LOG_SHEET) if r and r[0] != TARGET]
    rows.append([TARGET, datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M'), str(n)])
    isl.api(f"{base}/values/{isl.urllib.parse.quote(f'{LOG_SHEET}!A1:C')}:clear", at, 'POST', {})
    isl.api(f"{base}/values/{isl.urllib.parse.quote(f'{LOG_SHEET}!A1')}?valueInputOption=RAW", at, 'PUT',
            {'values': [['対象月', '作成日時', '人数']] + rows})


def main():
    from playwright.sync_api import sync_playwright
    if SKIP_IF_DONE:
        at0 = isl.access_token()
        ss0 = os.environ.get('SHEET_ID') or open(os.path.join(isl.HERE, 'sheet_id.txt')).read().strip()
        if TARGET in done_months(ss0, at0):
            print(f'{TARGET}の誕生日リストはもう作ってあるので、何もしません')
            return
    if not os.environ.get('URAKATA_EMAIL') or not os.environ.get('URAKATA_PASSWORD'):
        sys.exit('URAKATA_EMAIL と URAKATA_PASSWORD を環境変数に設定してください')
    os.makedirs('out', exist_ok=True)
    tm = int(TARGET[5:])
    # 直近1年＝対象月を含めて13か月（1日に動くと対象月はほぼ空。前の12か月がまるごと入る）
    span = months_back(TARGET, 13)
    customers = None
    for attempt in range(1, 4):                  # うらかたさんが開かない夜がある（2026-10-13 60秒タイムアウト）
        course, buy_days, last_visit, service_names = set(), {}, {}, {}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(viewport={'width': 1400, 'height': 6000}, locale='ja-JP')
                page = ctx.new_page()
                try:
                    fu.login(page, 'out')
                    for y, m in span:
                        rows = read_month(page, y, m)
                        print(f'  {y}-{m:02d}: {len(rows)}件')
                        for tab, d, name, cust in rows:
                            k = norm(cust)
                            if tab == 'サービス':
                                service_names[name] = service_names.get(name, 0) + 1
                            if tab == 'コース':
                                course.add(k)
                            elif tab == '物販':
                                buy_days.setdefault(k, set()).add(d)
                            # 来店日：毎月1日の物販は定期便の発送なので来店に数えない
                            if not (tab == '物販' and d.endswith('/01')):
                                if d > last_visit.get(k, ''):
                                    last_visit[k] = d
                    customers = read_customers(page)
                finally:
                    browser.close()
            if len(customers) < 40:
                raise RuntimeError(f'顧客一覧が{len(customers)}人しか読めませんでした')
            break
        except BaseException as e:               # sys.exit も含めてやり直す
            if isinstance(e, KeyboardInterrupt):
                raise
            print(f'⚠️ {attempt}回目は失敗しました（{str(e).splitlines()[0][:120]}）')
            customers = None
            if attempt < 3:
                time.sleep(60)
    if customers is None:
        sys.exit('3回試しましたが、うらかたさんから読めませんでした')

    print(f'サービスのメニュー名: {service_names}')
    with_bd = [c for c in customers if c['誕生日']]
    print(f'顧客管理 {len(customers)}人（誕生日あり {len(with_bd)}人）')
    if not with_bd:
        sys.exit('顧客一覧が少なすぎます。読み込みが途中で止まった可能性があります')
    real = course | {k for k, ds in buy_days.items() if len(ds) >= 2}
    known = {norm(c['名前']) for c in customers}
    missing = len([k for k in real if k not in known])
    if missing:
        print(f'⚠️ 売上にいて顧客管理に見つからない名前 {missing}人（表記ゆれの可能性。名前は出しません）')

    at = isl.access_token()
    ssid = os.environ.get('SHEET_ID') or open(os.path.join(isl.HERE, 'sheet_id.txt')).read().strip()
    staff = staff_names(ssid, at)

    month_people = [c for c in with_bd if int(c['誕生日'][1]) == tm]
    out, n_staff, n_drop = [], 0, 0
    for c in month_people:
        k = norm(c['名前'])
        if 'スタッフ' in c['メモ'] or k in staff:
            n_staff += 1
            continue
        if k not in real:
            n_drop += 1
            continue
        y, m, d = c['誕生日']
        out.append([TARGET, c['名前'], f'{y}/{m}/{d}', last_visit.get(k, ''),
                    datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M')])
    out.sort(key=lambda r: r[2][5:])
    print(f'{TARGET}が誕生日 {len(month_people)}人 → スタッフ除外 {n_staff}人・'
          f'コースなし・商品2回未満で除外 {n_drop}人 → 載せる {len(out)}人')
    if DRY:
        print('（--dry なので書き込みません）')
        return
    n = write_sheet(ssid, at, out)
    record_done(ssid, at, n)
    print(f'✅ 「{SHEET}」シートに{n}人を書き込みました')


if __name__ == '__main__':
    main()
