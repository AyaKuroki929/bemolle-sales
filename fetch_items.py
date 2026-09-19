#!/usr/bin/env python3
"""うらかたさんの「商品管理」から商品一覧を取って、売上日報の商品マスタに反映する。

  python3 fetch_items.py [--dry]

うらかたさんが持っているのは 商品名・ブランド・単価 の3つだけ。
税率と仕入値はうらかたさんに無いので、**すでにある行のものは触らない**。
新しく増えた商品は税率10%で入れる（食品なら彩さんが設定タブで8%に直す）。
うらかたさんから消えた商品はこちらでは消さない（過去の売上の税率を引くのに要るため）。

⚠️ 一覧は少しずつしか描画されず、「ブランド順」と「アラート順」で中身が違う。
   両方を見て、見えたものをためていく。
"""
import os, re, sys, json, unicodedata, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.path.expanduser('~/.google_drive_token.json')
BASE = 'https://urakatasan.jp'

ROW_RE = re.compile(r'^(.*?)\s*ブランド：(.*?)\s*単価：([\d,]+)\s*円?\s*メモ：(.*?)在庫数：(-?[\d,]+)')

# 仕入値の掛け率（2026-09-19 彩さん）。H.R.は5掛け、それ以外は6掛け。
# すでに仕入値が入っている行は触らない（棚卸しの実額が入っていることがあるため）
def shiire(brand, price):
    return round(price * (0.5 if brand == 'H.R.' else 0.6))


def keyname(s):
    return re.sub(r'[\s　]+', '', unicodedata.normalize('NFKC', str(s)))


def access_token():
    raw = os.environ.get('GOOGLE_TOKEN')
    t = json.loads(raw) if raw else json.load(open(TOKEN))
    d = urllib.parse.urlencode({'client_id': t['client_id'], 'client_secret': t['client_secret'],
                                'refresh_token': t['refresh_token'], 'grant_type': 'refresh_token'}).encode()
    return json.load(urllib.request.urlopen('https://oauth2.googleapis.com/token', d))['access_token']


def api(url, at, method='GET', body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Authorization': 'Bearer ' + at, 'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req))


def click_text(page, label):
    for el in page.query_selector_all('div,span,button,a'):
        try:
            if (el.text_content() or '').strip() == label and el.is_visible():
                el.click()
                return True
        except Exception:
            continue
    return False


def harvest(page, found):
    """いま描画されている行を全部ためる（一覧が複数あるので全部見る）"""
    for g in page.query_selector_all('[class*="RepeatingGroup"]'):
        for el in g.query_selector_all(':scope > *'):
            t = re.sub(r'\s+', ' ', el.text_content() or '').strip()
            m = ROW_RE.match(t)
            if m:
                found[keyname(m.group(1))] = (m.group(1).strip(), m.group(2).strip(),
                                              int(m.group(3).replace(',', '')),
                                              int(m.group(5).replace(',', '')))
    return len(found)


def scroll_and_harvest(page, found, rounds=24):
    last, same = -1, 0
    for _ in range(rounds):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(700)
        n = harvest(page, found)
        if n == last:
            same += 1
            if same >= 6:
                break
        else:
            same, last = 0, n
    return len(found)


def scrape():
    from playwright.sync_api import sync_playwright
    email = os.environ.get('URAKATA_EMAIL', '')
    password = os.environ.get('URAKATA_PASSWORD', '')
    if not email or not password:
        sys.exit('URAKATA_EMAIL と URAKATA_PASSWORD を環境変数に設定してください')
    found = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1400, 'height': 3000}, locale='ja-JP')
        page = ctx.new_page()
        try:
            page.goto(BASE, wait_until='networkidle', timeout=60000)
            page.wait_for_timeout(3000)

            # ── ログイン（売上を取る方と同じ手順。すでにログイン済みなら飛ばす）
            if not page.query_selector('text=売上管理'):
                for label in ['ログイン', 'ログイン / 新規登録', 'Log in', 'サインイン']:
                    if click_text(page, label):
                        page.wait_for_timeout(2500)
                        break
                mail = page.query_selector('input[type=email]') or page.query_selector('input[name*=mail i]')
                pw = page.query_selector('input[type=password]')
                if not (mail and pw):
                    page.screenshot(path='out/items_login_error.png', full_page=True)
                    sys.exit('ログイン欄が見つかりませんでした')
                mail.fill(email)
                pw.fill(password)
                pw.press('Enter')
                page.wait_for_timeout(6000)
                if not page.query_selector('text=売上管理'):
                    for label in ['ログイン', 'Log in', '送信']:
                        if click_text(page, label):
                            break
                    page.wait_for_timeout(6000)
            if not page.query_selector('text=売上管理'):
                page.screenshot(path='out/items_login_error.png', full_page=True)
                sys.exit('ログインできませんでした')

            page.goto(BASE + '/notifications_item', wait_until='networkidle', timeout=60000)
            page.wait_for_timeout(6000)
            harvest(page, found)
            print(f'  はじめに見えた分: {len(found)}件')
            scroll_and_harvest(page, found)
            print(f'  アラート順でためた分: {len(found)}件')

            # 「ブランド順」に切り替えると別の一覧が出てきて、こちらの方が多い
            if click_text(page, 'ブランド順'):
                page.wait_for_timeout(6000)
                page.mouse.wheel(0, -50000)
                page.wait_for_timeout(1500)
                harvest(page, found)
                scroll_and_harvest(page, found, rounds=40)
                print(f'  ブランド順まで見てためた分: {len(found)}件')
            else:
                print('  ⚠️ ブランド順のボタンが見つかりませんでした')
        finally:
            browser.close()
    return found


def main():
    dry = '--dry' in sys.argv
    os.makedirs('out', exist_ok=True)
    found = scrape()
    if len(found) < 20:
        sys.exit(f'取れた商品が {len(found)}件しかありません。画面の作りが変わった可能性があります')

    at = access_token()
    ssid = os.environ.get('SHEET_ID') or open(os.path.join(HERE, 'sheet_id.txt')).read().strip()
    rng = urllib.parse.quote("'商品マスタ'!A1:Z")
    v = api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values/{rng}', at).get('values', [])
    head = v[0]
    col = {h: i for i, h in enumerate(head)}
    rows = [(r + [''] * len(head))[:len(head)] for r in v[1:] if r and str(r[0]).strip()]
    by = {keyname(r[0]): r for r in rows}
    order = max([int(r[col['表示順']] or 0) for r in rows] + [0])

    import datetime
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime('%Y-%m-%d')

    added, changed = [], []
    for k, (name, brand, price, stock) in found.items():
        r = by.get(k)
        if r is None:
            new = [''] * len(head)
            new[col['商品名']] = name
            new[col['税率']] = 10          # うらかたさんに税率が無いので既定10%
            new[col['税抜単価']] = price
            new[col['仕入値']] = shiire(brand, price) if price > 0 else ''
            new[col['ブランド']] = brand
            if '在庫数' in col:
                new[col['在庫数']] = stock
            order += 1
            new[col['表示順']] = order
            new[col['有効']] = True
            if '最終確認日' in col:
                new[col['最終確認日']] = today
            rows.append(new); by[k] = new
            added.append(k)
            continue
        diff = []
        if str(r[col['税抜単価']] or 0) != str(price) and price > 0:
            diff.append(f'単価 {r[col["税抜単価"]]}→{price}'); r[col['税抜単価']] = price
        if (r[col['ブランド']] or '') != brand:
            diff.append(f'ブランド {r[col["ブランド"]] or "空"}→{brand}'); r[col['ブランド']] = brand
        if r[col['商品名']] != name:
            diff.append(f'名前 {r[col["商品名"]]}→{name}'); r[col['商品名']] = name
        if '在庫数' in col and str(r[col['在庫数']]) != str(stock):
            r[col['在庫数']] = stock          # 在庫は毎晩そのまま上書き（棚卸しに使う）
        if not str(r[col['仕入値']]).strip() and price > 0:
            r[col['仕入値']] = shiire(brand, price)
            diff.append(f'仕入値を {r[col["仕入値"]]:,} で埋めた')
        if '最終確認日' in col:
            r[col['最終確認日']] = today
        if diff:
            changed.append(f'{name}: ' + ' / '.join(diff))

    gone_keys = [k for k in by if k not in found]
    gone = [by[k][col['商品名']] for k in gone_keys]

    # 同じ晩に「消えた1件」と「増えた1件」があって、ブランドも単価も同じなら改名とみなす。
    # 名前で照合しているので、放っておくと古い名前と新しい名前の2つに増えてしまう（2026-09-19 彩さん）
    renamed = []
    if '最終確認日' in col:
        seen_before = [k for k in gone_keys if str(by[k][col['最終確認日']]).strip()]
        for gk in list(seen_before):
            g = by[gk]
            cand = [ak for ak in added
                    if by[ak][col['ブランド']] == g[col['ブランド']]
                    and str(by[ak][col['税抜単価']]) == str(g[col['税抜単価']])]
            if len(cand) != 1:
                continue
            ak = cand[0]; a_row = by[ak]
            # 古い行が持っていた 税率・仕入値・表示順 を新しい行へ引き継ぐ
            for h in ['税率', '仕入値', '表示順']:
                if h in col and str(g[col[h]]).strip():
                    a_row[col[h]] = g[col[h]]
            renamed.append(f'{g[col["商品名"]]} → {a_row[col["商品名"]]}')
            rows.remove(g); del by[gk]
            gone_keys.remove(gk); gone.remove(g[col['商品名']])
            added.remove(ak)
    print(f'うらかたさん {len(found)}件 / 商品マスタ {len(rows)}件')
    if renamed:
        print(f'  名前が変わったとみて つなぎ直した: {len(renamed)}件  ' + ' / '.join(renamed))
    print(f'  新しく足す: {len(added)}件'
          + ('  ' + ' / '.join(by[k][col['商品名']] for k in added[:8]) if added else ''))
    print(f'  中身を直す: {len(changed)}件')
    for c in changed[:10]:
        print('    ・' + c)
    print(f'  うらかたさんに無いがこちらに残すもの: {len(gone)}件'
          + ('  ' + ' / '.join(gone[:8]) if gone else ''))
    if dry:
        print('（--dry なので書き込みません）')
        return
    # 在庫数は毎晩変わるので、変更が無くても書き戻す
    api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values/' +
        urllib.parse.quote("'商品マスタ'!A2:Z") + ':clear', at, 'POST', {})
    api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values:batchUpdate', at, 'POST',
        {'valueInputOption': 'RAW', 'data': [{'range': "'商品マスタ'!A2", 'values': rows}]})
    # 棚卸しの画面に「いつ時点の在庫か」を出すため
    import datetime
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    stamp = now.strftime('%Y-%m-%d %H:%M')
    sv = api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values/'
             + urllib.parse.quote("'設定'!A1:B"), at).get('values', [])
    srows = [r for r in sv[1:] if r and str(r[0]).strip() and str(r[0]) != '在庫取込日時']
    srows.append(['在庫取込日時', stamp])
    api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values/'
        + urllib.parse.quote("'設定'!A2:B") + ':clear', at, 'POST', {})
    api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values:batchUpdate', at, 'POST',
        {'valueInputOption': 'RAW', 'data': [{'range': "'設定'!A2", 'values': srows}]})
    print(f'書き込みました 商品マスタ {len(rows)}件（在庫は {stamp} 時点）')


if __name__ == '__main__':
    main()
