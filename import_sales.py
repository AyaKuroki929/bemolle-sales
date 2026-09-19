#!/usr/bin/env python3
"""うらかたさんから抜いたCSVを、売上日報のスプレッドシートに取り込む。
  python3 import_sales.py <まとめCSV> [--dry]                  … fetch_urakata.py の出力
  python3 import_sales.py <物販CSV> <サービス契約CSV> [--dry]   … 手作業で分けた場合
会計（日付＋顧客でまとめる）と明細を作る。入金は空のまま＝彩さんが画面で支払方法を入れる。
"""
import csv, json, sys, os, re, unicodedata, urllib.request, urllib.parse, datetime, collections

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.path.expanduser('~/.google_drive_token.json')

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

def keyname(s):
    """商品名の照合用。うらかたさんは「クレアスキンクリーム」、マスタは「クレアスキン クリーム」の
    ようにスペースの有無が揃っていないので、スペースと全角半角をそろえてから突き合わせる"""
    return re.sub(r'[\s　]+', '', unicodedata.normalize('NFKC', str(s)))

# 起動時は products.json。スプレッドシートの商品マスタが読めたらそちらで置き換える
_RAW = json.load(open(os.path.join(HERE, 'products.json'), encoding='utf-8'))['商品']
PRODUCTS = {keyname(p['名称']): p for p in _RAW}
PRODUCTS.setdefault(keyname('ボンバー'), {'単価': 8000, '税率': 8})


def load_master(ssid, at):
    """商品マスタ（商品名・税率・税抜単価）を大元にする。彩さんが設定タブで足した商品が
    その晩から効くようにするため。読めなければ products.json のまま続ける"""
    try:
        v = read(ssid, at, '商品マスタ')
    except Exception as e:
        print(f'⚠️ 商品マスタが読めませんでした（{e}）。products.json で続けます')
        return
    got = {}
    for r in v:
        r = pad(r, 7)
        if not str(r[0]).strip():
            continue
        if str(r[6]).upper() == 'FALSE':          # 有効=FALSE は使わない
            continue
        got[keyname(r[0])] = {'名称': r[0], '税率': int(r[1] or 10), '単価': int(r[2] or 0),
                              'ブランド': r[4]}
    if not got:
        print('⚠️ 商品マスタが空でした。products.json で続けます')
        return
    PRODUCTS.clear()
    PRODUCTS.update(got)
    print(f'商品マスタ {len(got)}件を読みました')


def product(name):
    return PRODUCTS.get(keyname(name), {})

def kubun(name):
    if 'セルマン' in name: return 'セルマン'
    if '下半身' in name or '上半身' in name: return '半身'
    if '幹細胞' in name or 'プラペン' in name: return 'プラペン'
    if '全身' in name: return '全身'
    return '対象外'

def load_unified(path):
    """fetch_urakata.py が書き出した1本のCSVを読む（区分＝物販/サービス/コース）"""
    items = []
    for r in csv.DictReader(open(path, encoding='utf-8-sig')):
        amt, qty = int(r['金額'] or 0), int(r['数量'] or 1)
        d, name, ku = r['日付'], r['名称'], r['区分']
        if ku == '物販':
            p = product(name)
            tanka, tax = p.get('単価'), p.get('税率', 10)
            teiki = d.endswith('/01') and tanka and amt == round(tanka * qty * 0.9)
            items.append({'日付': d, '顧客': r['顧客'], 'スタッフ': r['スタッフ'],
                          '種別': '定期便' if teiki else '物販', '名称': name, '数量': qty,
                          '区分': '定期便' if teiki else '物販', '税率': tax, '税抜': amt,
                          '備考': r.get('メモ', '')})
        elif ku == 'サービス':
            items.append({'日付': d, '顧客': r['顧客'], 'スタッフ': r['スタッフ'],
                          '種別': '施術', '名称': name, '数量': 1, '区分': kubun(name),
                          '税率': 10, '税抜': amt, '備考': r.get('メモ', '')})
        else:  # コース
            shouka = r.get('状態') == '消化'
            items.append({'日付': d, '顧客': r['顧客'], 'スタッフ': r['スタッフ'],
                          '種別': '施術' if shouka else '契約', '名称': name, '数量': 1,
                          '区分': kubun(name) if shouka else '通常契約',
                          '税率': 10, '税抜': amt, '備考': r.get('メモ', '')})
    return items


def load(bussan_csv, sc_csv):
    items = []
    for r in csv.DictReader(open(bussan_csv, encoding='utf-8-sig')):
        amt, qty = int(r['金額'] or 0), int(r['数量'] or 1)
        p = product(r['商品'])
        tanka, tax = p.get('単価'), p.get('税率', 10)
        # 定期便＝日付が1日 かつ 定価×数量の90%ちょうど
        teiki = r['日付'].endswith('/01') and tanka and amt == round(tanka * qty * 0.9)
        items.append({'日付': r['日付'], '顧客': r['顧客'], 'スタッフ': r['スタッフ'],
                      '種別': '定期便' if teiki else '物販', '名称': r['商品'], '数量': qty,
                      '区分': '定期便' if teiki else '物販', '税率': tax, '税抜': amt, '備考': r.get('メモ', '')})
    for r in csv.DictReader(open(sc_csv, encoding='utf-8-sig')):
        kind = '契約' if r['区分'] == '契約' else '施術'
        items.append({'日付': r['日付'], '顧客': r['顧客'], 'スタッフ': r['スタッフ'],
                      '種別': kind, '名称': r['名称'], '数量': 1,
                      '区分': '通常契約' if kind == '契約' else kubun(r['名称']),
                      '税率': 10, '税抜': int(r['金額'] or 0), '備考': ''})
    return items

def read(ssid, at, name):
    u = (f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values/'
         + urllib.parse.quote(f"'{name}'!A2:Z"))
    return api(u, at).get('values', [])

def pad(row, n):
    return (row + [''] * n)[:n]

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry' in sys.argv
    at = access_token()
    ssid = os.environ.get('SHEET_ID') or open(os.path.join(HERE, 'sheet_id.txt')).read().strip()
    load_master(ssid, at)                      # 税率と定価は商品マスタを大元にする
    if len(args) == 1:
        items = load_unified(args[0])          # うらかたさんから自動取得した1本のCSV
    else:
        items = load(args[0], args[1])         # 手作業で分けた2本のCSV
    groups = collections.OrderedDict()
    for it in sorted(items, key=lambda x: (x['日付'], x['顧客'])):
        groups.setdefault((it['日付'], it['顧客']), []).append(it)

    months = sorted({it['日付'].replace('/', '-')[:7] for it in items})
    if not months:
        print('CSVが空です。何も書き換えません'); return
    print('入れ替える月:', ', '.join(months))

    old_sales = [pad(r, 11) for r in read(ssid, at, '会計')  if r and r[0]]
    old_det   = [pad(r, 13) for r in read(ssid, at, '明細')  if r and r[0]]
    paid_ids  = {r[1] for r in read(ssid, at, '入金') if len(r) > 1 and r[1]}

    # 今回入れ替える月の既存行＝会計IDと彩さんが入れた列を引き継ぐための材料
    target   = lambda d: d[:7] in months
    keep_s   = [r for r in old_sales if not target(r[1])]
    keep_d   = [r for r in old_det   if not target(r[2])]
    prev     = {(r[1], r[2]): r for r in old_sales if target(r[1])}
    used_seq = collections.Counter()
    for r in old_sales:
        if r[0].startswith('S') and len(r[0]) >= 12:
            used_seq[r[0][1:9]] = max(used_seq[r[0][1:9]], int(r[0][9:12] or 0))

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sales, details, changed, added, total = [], [], [], 0, 0
    for (d, cust), its in groups.items():
        d = d.replace('/', '-')
        net = sum(i['税抜'] for i in its)
        gross = sum(round(i['税抜'] * (1 + i['税率'] / 100)) for i in its)
        staff = collections.Counter(i['スタッフ'] for i in its if i['スタッフ']).most_common(1)
        o = prev.pop((d, cust), None)
        if o:
            sid, apo, memo, made, state = o[0], o[4], o[5], o[9], o[8]
            # 金額が変わったのに支払が入っている＝黙って食い違わせない
            if sid in paid_ids and str(o[7]) != str(gross):
                # ログは公開リポジトリに残るので、名前は出さず会計IDだけにする
                state, _ = '要確認', changed.append(f'{sid} 税込{o[7]}→{gross}')
        else:
            used_seq[d.replace('-', '')] += 1
            sid = 'S' + d.replace('-', '') + f'{used_seq[d.replace("-", "")]:03d}'
            apo, memo, made, state = '', '', now, '未入力' if gross else '支払なし'
            added += 1
        sales.append([sid, d, cust, staff[0][0] if staff else '', apo, memo, net, gross, state, made, now])
        total += net
        for m, i in enumerate(its, 1):
            details.append([f'{sid}-{m:02d}', sid, d, i['種別'], i['名称'], i['数量'],
                            i['区分'], i['税率'], i['税抜'], round(i['税抜'] * (1 + i['税率'] / 100)),
                            i['スタッフ'], False, i['備考']])

    # うらかたさんから消えた会計は、支払方法が入っていてもこちらでも消す（2026-09-19 彩さん）
    gone = [o[0] for o in prev.values()]

    sales.sort(key=lambda r: (r[1], r[0]))
    details.sort(key=lambda r: (r[2], r[0]))
    allsales, alldet = keep_s + sales, keep_d + details
    allsales.sort(key=lambda r: (r[1], r[0]))
    alldet.sort(key=lambda r: (r[2], r[0]))

    print(f'今回の月: 会計 {len(sales)}件（新規 {added}件）/ 明細 {len(details)}件 '
          f'/ 税抜合計 {total:,}円')
    print(f'他の月をそのまま残す: 会計 {len(keep_s)}件 / 明細 {len(keep_d)}件')
    print('種別:', dict(collections.Counter(d[3] for d in details)))
    for c in changed: print('  ⚠️ 要確認:', c)
    if dry:
        for s in sales[:5]: print('  ', s[0], s[1], s[6:9])   # 名前は出さない（公開ログ対策）
        return
    # 会計が消えたら、その入金も残さない（集計に幽霊が残らないように）
    live = {r[0] for r in allsales}
    old_pay = [pad(r, 8) for r in read(ssid, at, '入金') if r and r[0]]
    allpay = [r for r in old_pay if r[1] in live]
    dropped = len(old_pay) - len(allpay)

    for name in ['会計', '明細', '入金']:
        api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values/' +
            urllib.parse.quote(f"'{name}'!A2:Z") + ':clear', at, 'POST', {})
    api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values:batchUpdate', at, 'POST',
        {'valueInputOption': 'RAW',
         'data': [{'range': "'会計'!A2", 'values': allsales},
                  {'range': "'明細'!A2", 'values': alldet}] +
                 ([{'range': "'入金'!A2", 'values': allpay}] if allpay else [])})
    if gone:
        print(f'うらかたさんから消えた会計 {len(gone)}件を、こちらからも消しました'
              + (f'（入金 {dropped}件も一緒に）' if dropped else ''))
    print(f'書き込みました 会計{len(allsales)}件 / 明細{len(alldet)}件: '
          'https://docs.google.com/spreadsheets/d/' + ssid + '/edit')
    if changed:
        sys.exit(9)   # 要確認が出たら失敗扱い＝LINEに飛ばす

if __name__ == '__main__':
    main()
