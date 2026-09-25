#!/usr/bin/env python3
"""うらかたさんの売上管理から、指定月の明細を取ってCSVに書き出す。
GitHub Actions（PCを開かなくても動く）でもローカルでも使える。

必要な環境変数:
  URAKATA_EMAIL, URAKATA_PASSWORD   … うらかたさんのログイン情報
使い方:
  python3 fetch_urakata.py 2026-08 [出力先フォルダ]
"""
import os, sys, csv, re, time

MONTH = sys.argv[1] if len(sys.argv) > 1 else time.strftime('%Y-%m')
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else '.'
YEAR, MON = MONTH.split('-')
BASE = 'https://urakatasan.jp'

ROW_RE = re.compile(
    r'^(.*?)日付：(\d{4}/\d{2}/\d{2})(?:数量：(\d*))?お客様：(.*?)様売上額：([\d,\-]+)円'
    r'(✅消化)?(?:メモ：(.*?))?(?:スタッフ：(.*?))?(?:編集|削除)')


# タブごとに一覧（RepeatingGroup）が別々に存在する。ページ全体を読むと3タブ分が混ざる
TAB_IDX = {'物販': 0, 'サービス': 1, 'コース': 2}
YM = f'{YEAR}/{MON}/'


def rg(page, tab):
    gs = page.query_selector_all('[class*="RepeatingGroup"]')
    if len(gs) <= TAB_IDX[tab]:
        sys.exit(f'{tab}の一覧が見つかりませんでした（一覧は{len(gs)}個しかありません）')
    return gs[TAB_IDX[tab]]


def parse_rows(page, tab):
    rows, other = [], 0
    for el in rg(page, tab).query_selector_all(':scope > *'):
        t = re.sub(r'\s', '', el.text_content() or '')
        m = ROW_RE.match(t)
        if not m:
            continue
        if not m.group(2).startswith(YM):          # 対象月以外が混じったら捨てる
            other += 1
            continue
        rows.append({'区分': tab, '日付': m.group(2), '名称': m.group(1),
                     '数量': m.group(3) or '1', '顧客': m.group(4),
                     '金額': m.group(5).replace(',', ''),
                     'スタッフ': (m.group(8) or '').strip(),
                     '状態': '消化' if m.group(6) else ('契約' if tab == 'コース' else ''),
                     'メモ': (m.group(7) or '').strip()})
    if other:
        print(f'    （{MONTH}以外の{other}件は除きました）')
    return rows


def load_all(page, tab):
    """一覧は少しずつしか描画されないので、最後まで増えなくなるまでスクロールする"""
    last, stable = -1, 0
    for _ in range(40):
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(900)
        n = len(rg(page, tab).query_selector_all(':scope > *'))
        if n == last:
            stable += 1
            if stable >= 4:
                break
        else:
            stable, last = 0, n
    return last


def click_text(page, label):
    for el in page.query_selector_all('div,span,button,a'):
        try:
            if (el.text_content() or '').strip() == label and el.is_visible():
                el.click()
                return True
        except Exception:
            continue
    return False


def main():
    from playwright.sync_api import sync_playwright
    email = os.environ.get('URAKATA_EMAIL', '')
    password = os.environ.get('URAKATA_PASSWORD', '')
    if not email or not password:
        sys.exit('URAKATA_EMAIL と URAKATA_PASSWORD を環境変数に設定してください')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # 縦に大きい画面にすると一覧が一度にたくさん描画される
        ctx = browser.new_context(viewport={'width': 1400, 'height': 6000}, locale='ja-JP')
        page = ctx.new_page()
        try:
            page.goto(BASE, wait_until='networkidle', timeout=60000)
            page.wait_for_timeout(3000)

            # ── ログイン（すでにログイン済みなら飛ばす）
            if not page.query_selector('text=売上管理'):
                for label in ['ログイン', 'ログイン / 新規登録', 'Log in', 'サインイン']:
                    if click_text(page, label):
                        page.wait_for_timeout(2500)
                        break
                mail = page.query_selector('input[type=email]') or page.query_selector('input[name*=mail i]')
                pw = page.query_selector('input[type=password]')
                if not (mail and pw):
                    page.screenshot(path=os.path.join(OUTDIR, 'login_error.png'), full_page=True)
                    sys.exit('ログイン欄が見つかりませんでした（login_error.png を確認）')
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
                page.screenshot(path=os.path.join(OUTDIR, 'login_error.png'), full_page=True)
                sys.exit('ログインできませんでした（login_error.png を確認）')

            # ── 売上管理へ
            # 年月の選択欄が描画されるまで待つ（固定5秒では間に合わない夜があった 2026-09-26）。
            # 出なければ1回だけ読み直す
            sels = []
            for attempt in range(2):
                page.goto(BASE + '/reports_income', wait_until='networkidle', timeout=60000)
                try:
                    page.wait_for_selector('select', timeout=40000)
                except Exception:
                    pass
                page.wait_for_timeout(3000)
                sels = page.query_selector_all('select')
                if len(sels) >= 2:
                    break
                print(f'年月の選択欄がまだ出ていません（{attempt + 1}回目）。読み直します')
            if len(sels) < 2:
                sys.exit('年月の選択欄が見つかりませんでした')
            sels[0].select_option(label=YEAR)
            page.wait_for_timeout(1500)
            sels[1].select_option(label=str(int(MON)))
            page.wait_for_timeout(4000)

            all_rows = []
            for tab in ['物販', 'サービス', 'コース']:
                click_text(page, tab)
                page.wait_for_timeout(3000)
                n = load_all(page, tab)
                got = parse_rows(page, tab)
                print(f'  {tab}: {len(got)}件（描画 {n}）')
                all_rows += got

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
