#!/usr/bin/env python3
"""うらかたさんの売上管理から、指定月の明細を取ってCSVに書き出す。
GitHub Actions（PCを開かなくても動く）でもローカルでも使える。

必要な環境変数:
  URAKATA_EMAIL, URAKATA_PASSWORD   … うらかたさんのログイン情報
使い方:
  python3 fetch_urakata.py 2026-08 [出力先フォルダ]

2026-10-18 うらかたさんが新システムに切り替わったので作り直した。
  ・旧システム（Bubble）は一覧の文字を正規表現で読んでいたが、新システムは画面の裏に
    データがそのまま入っている（window.__reactRouterContext.state.loaderData）。それを読む
  ・月の切り替えはURLで指定できる（/dashboard/income?period=month&date=2026-09）
  ・1明細の金額は「会計の金額」を正とする（旧システムの売上額と一致することを 2026-09 の
    4件で確認。明細の unitPrice は定価のままのことがある）
"""
import os, sys, csv, time, math

MONTH = sys.argv[1] if len(sys.argv) > 1 else time.strftime('%Y-%m')
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else '.'
YEAR, MON = MONTH.split('-')
BASE = 'https://urakatasan.jp'

KIND_TAB = {'product': '物販', 'ordered_product': '物販', 'service': 'サービス', 'course': 'コース'}


def login(page, outdir='.'):
    """うらかたさんにログインする（すでにログイン済みなら何もしない）"""
    email = os.environ.get('URAKATA_EMAIL', '')
    password = os.environ.get('URAKATA_PASSWORD', '')
    page.goto(BASE + '/dashboard/income', wait_until='networkidle', timeout=60000)
    if '/signin' in page.url or page.query_selector('input[type=password]'):
        mail = page.query_selector('input[type=email]') or page.query_selector('input[name=email]')
        pw = page.query_selector('input[type=password]')
        if not (mail and pw):
            page.screenshot(path=os.path.join(outdir, 'login_error.png'), full_page=True)
            sys.exit('ログイン欄が見つかりませんでした（login_error.png を確認）')
        mail.fill(email)
        pw.fill(password)
        pw.press('Enter')
        try:
            page.wait_for_url('**/dashboard**', timeout=60000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
    if '/signin' in page.url or not page.query_selector('text=売上管理'):
        page.screenshot(path=os.path.join(outdir, 'login_error.png'), full_page=True)
        sys.exit('ログインできませんでした（login_error.png を確認）')


def loader_data(page, url, key, tries=3):
    """ページを開いて、裏に入っているデータ（loaderData[key]）を取り出す"""
    for attempt in range(tries):
        page.goto(BASE + url, wait_until='networkidle', timeout=60000)
        try:
            page.wait_for_function(
                "k => window.__reactRouterContext && window.__reactRouterContext.state"
                " && window.__reactRouterContext.state.loaderData"
                " && window.__reactRouterContext.state.loaderData[k]",
                arg=key, timeout=40000)
            return page.evaluate("k => window.__reactRouterContext.state.loaderData[k]", key)
        except Exception:
            print(f'データがまだ出ていません（{attempt + 1}回目）。10秒おいて読み直します')
            page.wait_for_timeout(10000)
    sys.exit(f'{url} のデータが読めませんでした')


def fetch_month(page, year, mon):
    """その月の売上を、旧CSVと同じ列の辞書の一覧で返す。mon は '08' でも '8' でもよい"""
    ym = f'{int(year):04d}-{int(mon):02d}'
    data = loader_data(page, f'/dashboard/income?period=month&date={ym}', 'routes/dashboard/income')
    sel = data.get('selectedPeriod') or {}
    if not str(sel.get('startDate', '')).startswith(ym):
        sys.exit(f'{ym} を開いたつもりが {sel.get("label")} が出ています')
    rows, other, prorated = [], 0, 0
    for r in data.get('records', []):
        d = str(r.get('date', ''))
        if not d.startswith(ym):
            other += 1
            continue
        lines = r.get('lineItems') or []
        # 明細ごとの金額：コース消化は0円。それ以外は会計の金額を明細に割り付ける。
        # 明細が1つなら会計の金額そのもの（unitPrice は定価のままのことがある）。
        # 明細が複数で unitPrice×数量 の合計が会計の金額と違うときだけ按分する（端数は最後の行）
        sold = [l for l in lines if not l.get('isCourseRedemption')]
        total = sum(int(l.get('unitPrice') or 0) * int(l.get('quantity') or 1) for l in sold)
        amount = int(r.get('amount') or 0)
        amt_of = {}
        if len(sold) == 1:
            amt_of[id(sold[0])] = amount
        elif total == amount or not sold:
            for l in sold:
                amt_of[id(l)] = int(l.get('unitPrice') or 0) * int(l.get('quantity') or 1)
        else:
            prorated += 1
            acc = 0
            for i, l in enumerate(sold):
                v = int(l.get('unitPrice') or 0) * int(l.get('quantity') or 1)
                a = amount - acc if i == len(sold) - 1 else (math.floor(amount * v / total) if total else 0)
                amt_of[id(l)] = a
                acc += a
        for l in lines:
            tab = KIND_TAB.get(l.get('kind'), '物販')
            shouka = bool(l.get('isCourseRedemption'))
            rows.append({'区分': tab, '日付': d.replace('-', '/'), '名称': str(l.get('name') or '').strip(),
                         '数量': str(int(l.get('quantity') or 1)), '顧客': str(r.get('customer') or '').strip(),
                         '金額': '0' if shouka else str(amt_of.get(id(l), 0)),
                         'スタッフ': str(r.get('staff') or '').strip(),
                         '状態': '消化' if shouka else ('契約' if tab == 'コース' else ''),
                         'メモ': str(l.get('memo') or '').strip()})
    if other:
        print(f'    （{ym}以外の{other}件は除きました）')
    if prorated:
        print(f'    ⚠️ 明細が複数で金額が合わない会計 {prorated}件は会計の金額を按分しました')
    return rows, data


def main():
    from playwright.sync_api import sync_playwright
    email = os.environ.get('URAKATA_EMAIL', '')
    password = os.environ.get('URAKATA_PASSWORD', '')
    if not email or not password:
        sys.exit('URAKATA_EMAIL と URAKATA_PASSWORD を環境変数に設定してください')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1400, 'height': 2000}, locale='ja-JP')
        page = ctx.new_page()
        try:
            login(page, OUTDIR)
            all_rows, _ = fetch_month(page, YEAR, MON)
            for tab in ['物販', 'サービス', 'コース']:
                print(f'  {tab}: {sum(1 for r in all_rows if r["区分"] == tab)}件')
            os.makedirs(OUTDIR, exist_ok=True)
            out = os.path.join(OUTDIR, f'urakata_{MONTH}.csv')
            with open(out, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.DictWriter(f, ['区分', '日付', '名称', '数量', '顧客', '金額', 'スタッフ', '状態', 'メモ'])
                w.writeheader()
                w.writerows(all_rows)
            print(f'書き出しました: {out}（{len(all_rows)}件）')
            if not all_rows:
                page.screenshot(path=os.path.join(OUTDIR, 'empty.png'), full_page=True)
                sys.exit('1件も取れませんでした（empty.png を確認）')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
