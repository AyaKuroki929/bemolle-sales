#!/usr/bin/env python3
"""今月が誕生日のお客様を、売上日報のスプレッドシート「誕生日」シートに書き出す。
毎月1日に GitHub Actions（birthdays.yml）が動かす。売上日報の画面「誕生日」タブがこのシートを読む。

  python3 fetch_birthdays.py [2026-11] [--dry]

決まりごと（2026-10-13 彩さん）
  ・誕生日はうらかたさんの顧客管理から取る
  ・スタッフは外す（顧客管理のメモに「スタッフ」とある人／売上日報のスタッフ一覧にいる人）
  ・直近1年に、体験メニュー以外の記録（物販・コース・体験以外のサービス）が1つも無い人は外す
    ＝体験だけの人と、1年以上来ていない人が外れる

⚠️ このリポジトリは公開。ログにお客様の名前・誕生日を出さない（件数だけ出す）。
"""
import os, sys, re, datetime, unicodedata

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
DRY = '--dry' in sys.argv
JST = datetime.timezone(datetime.timedelta(hours=9))
TARGET = ARGS[0] if ARGS else datetime.datetime.now(JST).strftime('%Y-%m')
if not re.fullmatch(r'\d{4}-\d{2}', TARGET):
    sys.exit(f'月の形が違います: {TARGET}（例 2026-11）')
sys.argv = [sys.argv[0], TARGET, 'out']          # fetch_urakata は読み込み時に引数を見る
import fetch_urakata as fu
import import_sales as isl

SHEET = '誕生日'
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
    """その月の売上（物販・サービス・コース）を (区分, 日付, 名称, 顧客) で返す"""
    fu.open_month(page, y, m)
    ym = f'{y}/{m:02d}/'
    rows = []
    for tab in ['物販', 'サービス', 'コース']:
        fu.click_text(page, tab)
        page.wait_for_timeout(3000)
        fu.load_all(page, tab)
        for el in fu.rg(page, tab).query_selector_all(':scope > *'):
            t = re.sub(r'\s', '', el.text_content() or '')
            mm = fu.ROW_RE.match(t)
            if mm and mm.group(2).startswith(ym):
                rows.append((tab, mm.group(2), mm.group(1), mm.group(4)))
    return rows


def read_customers(page):
    """顧客管理の全員を {名前, 誕生日, メモ} で返す"""
    page.goto(fu.BASE + '/interactions_costumer', wait_until='networkidle', timeout=60000)
    page.wait_for_timeout(4000)
    fu.click_text(page, '全てのお客様')
    page.wait_for_timeout(4000)
    page.mouse.move(700, 1500)
    last, stable = -1, 0
    for _ in range(400):                         # 本物のホイール操作でしか続きが読み込まれない
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(900)
        g = page.query_selector('[class*="RepeatingGroup"]')
        n = len(g.query_selector_all(':scope > *')) if g else 0
        if n == last:
            stable += 1
            if stable >= 6:
                break
        else:
            stable, last = 0, n
    g = page.query_selector('[class*="RepeatingGroup"]')
    if not g:
        sys.exit('顧客一覧が見つかりませんでした')
    out = []
    for el in g.query_selector_all(':scope > *'):
        t = re.sub(r'\s', '', el.text_content() or '')
        nm = re.match(r'^(.+?)様', t)
        if not nm:
            continue
        bd = re.search(r'誕生日：(\d{4})/(\d{2})/(\d{2})', t)
        memo = re.search(r'メモ：(.*?)(?:編集|$)', t)
        out.append({'名前': nm.group(1), '誕生日': bd.groups() if bd else None,
                    'メモ': memo.group(1) if memo else ''})
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


def main():
    from playwright.sync_api import sync_playwright
    if not os.environ.get('URAKATA_EMAIL') or not os.environ.get('URAKATA_PASSWORD'):
        sys.exit('URAKATA_EMAIL と URAKATA_PASSWORD を環境変数に設定してください')
    os.makedirs('out', exist_ok=True)
    tm = int(TARGET[5:])
    # 直近1年＝対象月を含めて13か月（1日に動くと対象月はほぼ空。前の12か月がまるごと入る）
    span = months_back(TARGET, 13)
    real, last_visit, service_names = set(), {}, {}

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
                    taiken = (tab == 'サービス' and '体験' in name)
                    if not taiken:
                        real.add(k)
                    # 来店日：毎月1日の物販は定期便の発送なので来店に数えない
                    if not (tab == '物販' and d.endswith('/01')):
                        if d > last_visit.get(k, ''):
                            last_visit[k] = d
            customers = read_customers(page)
        finally:
            browser.close()

    print(f'サービスのメニュー名: {service_names}')
    with_bd = [c for c in customers if c['誕生日']]
    print(f'顧客管理 {len(customers)}人（誕生日あり {len(with_bd)}人）')
    if len(customers) < 40 or not with_bd:
        sys.exit('顧客一覧が少なすぎます。読み込みが途中で止まった可能性があります')
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
          f'体験のみ／1年来店なし除外 {n_drop}人 → 載せる {len(out)}人')
    if DRY:
        print('（--dry なので書き込みません）')
        return
    n = write_sheet(ssid, at, out)
    print(f'✅ 「{SHEET}」シートに{n}人を書き込みました')


if __name__ == '__main__':
    main()
