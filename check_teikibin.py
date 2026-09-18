#!/usr/bin/env python3
"""定期便の答え合わせ。

うらかたさんから取り込んだ「定期便」（売上日報スプレッドシートの明細）と、
「サブスク個数把握」スプレッドシートのその月のタブ（B列=お客様 / Q列=金額 / R列=担当）を
お客様ごとに突き合わせる。

  python3 check_teikibin.py [2026-09] [--quiet]

食い違いが1件でもあれば終了コード9。GitHub Actions 側でそれをLINE通知に使う。
合っていれば何も言わない（無音）。
"""
import json, sys, os, re, urllib.request, urllib.parse, collections, unicodedata, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.path.expanduser('~/.google_drive_token.json')
SUBSC_ID = '1vxJIQvEI-VllkxL09lAj-NbfZcP9kKKwKYz_tTkH5u0'   # サブスク個数把握


def access_token():
    raw = os.environ.get('GOOGLE_TOKEN')
    t = json.loads(raw) if raw else json.load(open(TOKEN))
    d = urllib.parse.urlencode({'client_id': t['client_id'], 'client_secret': t['client_secret'],
                                'refresh_token': t['refresh_token'], 'grant_type': 'refresh_token'}).encode()
    return json.load(urllib.request.urlopen('https://oauth2.googleapis.com/token', d))['access_token']


def values(ssid, rng, at):
    u = (f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values/'
         + urllib.parse.quote(rng))
    req = urllib.request.Request(u, headers={'Authorization': 'Bearer ' + at})
    return json.load(urllib.request.urlopen(req)).get('values', [])


def rows(ssid, name, at):
    v = values(ssid, f"'{name}'!A1:Z", at)
    if not v:
        return []
    h = v[0]
    return [{h[i]: (r[i] if i < len(r) else '') for i in range(len(h))} for r in v[1:] if any(r)]


def norm(s):
    """スペース・全角半角をそろえる"""
    return re.sub(r'[\s　]+', '', unicodedata.normalize('NFKC', str(s)))


def person(s):
    """「今井さん」「今井佐季様」→「今井佐季」と突き合わせるための見出し"""
    return re.sub(r'(さん|様|ちゃん)$', '', norm(s))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    month = args[0] if args else datetime.datetime.now().strftime('%Y-%m')
    at = access_token()
    ssid = os.environ.get('SHEET_ID') or open(os.path.join(HERE, 'sheet_id.txt')).read().strip()

    # ① 売上日報の明細から、その月の定期便をお客様ごとに合計
    sales = {s['会計ID']: s for s in rows(ssid, '会計', at)}
    mine = collections.defaultdict(int)
    for r in rows(ssid, '明細', at):
        if r['種別'] != '定期便' or str(r['日付'])[:7] != month:
            continue
        cust = sales.get(r['会計ID'], {}).get('顧客名', '')
        mine[person(cust)] += int(r['税抜金額'] or 0)

    # ② サブスク個数把握のその月のタブ（B列=お客様 / Q列=金額）
    y, m = month.split('-')
    tab = f'{int(y)}年{int(m)}月'
    try:
        v = values(SUBSC_ID, f"'{tab}'!A1:R60", at)
    except Exception as e:
        print(f'🚨 サブスク個数把握に「{tab}」のタブがありません（{e}）')
        sys.exit(9)
    theirs = collections.defaultdict(int)
    for r in v[3:]:
        r = (list(r) + [''] * 18)[:18]
        name = person(r[1])
        if not name or name in ('合計', '計'):
            continue
        amt = int(re.sub(r'[^\d-]', '', str(r[16])) or 0)
        theirs[name] += amt

    if not theirs:
        print(f'🚨 サブスク個数把握「{tab}」にお客様の行がありません')
        sys.exit(9)

    # ③ 突き合わせ（サブスク表は苗字だけのことがあるので、前方一致も見る）
    used, diffs = set(), []
    for name, amt in sorted(theirs.items()):
        hit = mine.get(name)
        key = name
        if hit is None:
            cands = [k for k in mine if k.startswith(name) and k not in used]
            if len(cands) == 1:
                key, hit = cands[0], mine[cands[0]]
            elif len(cands) > 1:
                diffs.append(f'{name}様：うらかたさんに同じ苗字が{len(cands)}人いて決められません')
                continue
        if hit is None:
            if amt:
                diffs.append(f'{name}様：サブスク表 {amt:,}円 / うらかたさんに記録なし')
            continue
        used.add(key)
        if hit != amt:
            diffs.append(f'{name}様：サブスク表 {amt:,}円 / うらかたさん {hit:,}円（差 {hit-amt:+,}円）')
    for name, amt in sorted(mine.items()):
        if name not in used and amt:
            diffs.append(f'{name}様：うらかたさん {amt:,}円 / サブスク表に記録なし')

    total_mine, total_theirs = sum(mine.values()), sum(theirs.values())
    print(f'{month} の定期便　うらかたさん {total_mine:,}円（{len(mine)}名）'
          f' / サブスク表 {total_theirs:,}円（{len(theirs)}名）')
    if not diffs:
        print('✅ 全員一致')
        return
    print(f'⚠️ 食い違い {len(diffs)}件')
    for d in diffs:
        print('  ・' + d)
    sys.exit(9)


if __name__ == '__main__':
    main()
