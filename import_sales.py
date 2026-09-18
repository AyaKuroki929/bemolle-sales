#!/usr/bin/env python3
"""うらかたさんから抜いたCSVを、売上日報のスプレッドシートに取り込む。
  python3 import_sales.py <物販CSV> <サービス契約CSV> [--dry]
会計（日付＋顧客でまとめる）と明細を作る。入金は空のまま＝彩さんが画面で支払方法を入れる。
"""
import csv, json, sys, os, urllib.request, urllib.parse, datetime, collections

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.path.expanduser('~/.google_drive_token.json')

def access_token():
    t = json.load(open(TOKEN))
    d = urllib.parse.urlencode({'client_id': t['client_id'], 'client_secret': t['client_secret'],
                                'refresh_token': t['refresh_token'], 'grant_type': 'refresh_token'}).encode()
    return json.load(urllib.request.urlopen('https://oauth2.googleapis.com/token', d))['access_token']

def api(url, at, method='GET', body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Authorization': 'Bearer ' + at, 'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req))

PRODUCTS = {p['名称']: p for p in json.load(open(os.path.join(HERE, 'products.json'), encoding='utf-8'))['商品']}
PRODUCTS.setdefault('ボンバー', {'単価': 8000, '税率': 8})

def kubun(name):
    if 'セルマン' in name: return 'セルマン'
    if '下半身' in name or '上半身' in name: return '半身'
    if '幹細胞' in name or 'プラペン' in name: return 'プラペン'
    if '全身' in name: return '全身'
    return '対象外'

def load(bussan_csv, sc_csv):
    items = []
    for r in csv.DictReader(open(bussan_csv, encoding='utf-8-sig')):
        amt, qty = int(r['金額'] or 0), int(r['数量'] or 1)
        p = PRODUCTS.get(r['商品'], {})
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

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry' in sys.argv
    items = load(args[0], args[1])
    groups = collections.OrderedDict()
    for it in sorted(items, key=lambda x: (x['日付'], x['顧客'])):
        groups.setdefault((it['日付'], it['顧客']), []).append(it)

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sales, details = [], []
    for n, ((d, cust), its) in enumerate(groups.items(), 1):
        sid = 'S' + d.replace('/', '') + f'{n:03d}'
        net = sum(i['税抜'] for i in its)
        gross = sum(round(i['税抜'] * (1 + i['税率'] / 100)) for i in its)
        staff = collections.Counter(i['スタッフ'] for i in its if i['スタッフ']).most_common(1)
        sales.append([sid, d.replace('/', '-'), cust, staff[0][0] if staff else '', '', '',
                      net, gross, '未入力' if gross else '支払なし', now, now])
        for m, i in enumerate(its, 1):
            details.append([f'{sid}-{m:02d}', sid, d.replace('/', '-'), i['種別'], i['名称'], i['数量'],
                            i['区分'], i['税率'], i['税抜'], round(i['税抜'] * (1 + i['税率'] / 100)),
                            i['スタッフ'], False, i['備考']])

    print(f'会計 {len(sales)}件 / 明細 {len(details)}件 / 税抜合計 {sum(s[6] for s in sales):,}円')
    byk = collections.Counter(d[3] for d in details)
    print('種別:', dict(byk))
    if dry:
        for s in sales[:5]: print('  ', s[:5], s[6:9])
        return
    at = access_token()
    sid_file = os.path.join(HERE, 'sheet_id.txt')
    ssid = open(sid_file).read().strip()
    api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values/' +
        urllib.parse.quote("'会計'!A2:Z") + ':clear', at, 'POST', {})
    api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values/' +
        urllib.parse.quote("'明細'!A2:Z") + ':clear', at, 'POST', {})
    api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values:batchUpdate', at, 'POST',
        {'valueInputOption': 'RAW',
         'data': [{'range': "'会計'!A2", 'values': sales}, {'range': "'明細'!A2", 'values': details}]})
    print('取り込みました: https://docs.google.com/spreadsheets/d/' + ssid + '/edit')

if __name__ == '__main__':
    main()
