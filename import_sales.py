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

def backup_sheet(ssid, at, keep_days=7):
    """スプレッドシートをGoogleドライブに丸ごとコピーして控えにする。古い控えは消す"""
    try:
        today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime('%Y-%m-%d')
        folder_name = '売上日報の控え'
        q = urllib.parse.quote(f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false")
        found = api(f'https://www.googleapis.com/drive/v3/files?q={q}&fields=files(id)', at).get('files', [])
        if found:
            fid = found[0]['id']
        else:
            fid = api('https://www.googleapis.com/drive/v3/files?fields=id', at, 'POST',
                      {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'})['id']
        q2 = urllib.parse.quote(f"'{fid}' in parents and trashed=false")
        olds = api(f'https://www.googleapis.com/drive/v3/files?q={q2}&fields=files(id,name)', at).get('files', [])
        name = f'ベモーレ売上日報_控え_{today}'
        if not any(f['name'] == name for f in olds):          # 1日1つだけ（同じ日に何度走っても増やさない）
            api(f'https://www.googleapis.com/drive/v3/files/{ssid}/copy?fields=id', at, 'POST',
                {'name': name, 'parents': [fid]})
            olds.append({'id': '', 'name': name})
        # 古い控えを消す
        limit = (datetime.datetime.utcnow() + datetime.timedelta(hours=9) - datetime.timedelta(days=keep_days)).strftime('%Y-%m-%d')
        removed = 0
        for f in olds:
            d = f['name'].split('_')[-1]
            if d < limit and f['id']:
                api(f'https://www.googleapis.com/drive/v3/files/{f["id"]}', at, 'PATCH', {'trashed': True}); removed += 1
        print(f'控えを取りました（{today}・{len(olds) - removed}日分を保管）')
    except Exception as e:
        # 控えが取れなくても取り込みは続ける。ただし理由は残す
        print(f'⚠️ 控えが取れませんでした（{e}）。取り込みは続けます')

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
        # 会計の担当者は、明細の担当がひとつに揃っているときだけ入れる。
        # 揃っていなければ空にする（代表を1人選ぶと、担当なしの明細まで
        # その人がやったように見えてしまう。2026-09-19 彩さん指摘）
        names = {i['スタッフ'] or '' for i in its}
        one = list(names)[0] if len(names) == 1 else ''
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
        sales.append([sid, d, cust, one, apo, memo, net, gross, state, made, now])
        total += net
        for m, i in enumerate(its, 1):
            details.append([f'{sid}-{m:02d}', sid, d, i['種別'], i['名称'], i['数量'],
                            i['区分'], i['税率'], i['税抜'], round(i['税抜'] * (1 + i['税率'] / 100)),
                            i['スタッフ'], False, i['備考']])

    # ③ うらかたさんでお客様の名前を直しただけなら、支払方法を引き継ぐ（2026-09-21 彩さん「これで」）。
    #    同じ日に「消えた会計」と「増えた会計」があり、明細（商品・数量・税抜）が同じなら名前の修正とみなし、
    #    古い会計IDをそのまま使う＝入金のひも付けが切れない。要確認にもLINEにもしない
    def sig(rows):
        return tuple(sorted((str(r[4]), str(r[5]), str(r[8])) for r in rows))
    old_by_id = collections.defaultdict(list)
    for r in old_det:
        old_by_id[r[1]].append(r)
    new_ids = {r[0] for r in sales if r[9] == now}        # 今回はじめて作った会計
    renamed = []
    for key in list(prev.keys()):
        o = prev[key]
        if o[0] not in paid_ids:
            continue
        cands = [r for r in sales if r[0] in new_ids and r[1] == o[1]
                 and sig([d for d in details if d[1] == r[0]]) == sig(old_by_id.get(o[0], []))]
        if len(cands) != 1:
            continue
        n = cands[0]; new_id, old_id = n[0], o[0]
        n[0] = old_id                                      # 会計IDを古い方に戻す
        n[4], n[5], n[8], n[9] = o[4], o[5], o[8], o[9]    # アポインター・メモ・支払状態・作成日時を引き継ぐ
        for d in details:
            if d[1] == new_id:
                d[1] = old_id; d[0] = old_id + d[0][len(new_id):]
        renamed.append(f'{old_id}（名前の修正とみて引き継ぎ）')
        del prev[key]; new_ids.discard(new_id); added -= 1

    # うらかたさんから消えた会計は、支払方法が入っていてもこちらでも消す（2026-09-19 彩さん）
    gone = [o[0] for o in prev.values()]

    sales.sort(key=lambda r: (r[1], r[0]))
    details.sort(key=lambda r: (r[2], r[0]))
    allsales, alldet = keep_s + sales, keep_d + details
    allsales.sort(key=lambda r: (r[1], r[0]))
    alldet.sort(key=lambda r: (r[2], r[0]))

    # ② うらかたさんの画面が途中までしか読めなかったとき、読めなかった分を「消えた」とみなして
    #    支払方法ごと消してしまうのを防ぐ。前回より明細が2割以上減っていたら止める（LINEが飛ぶ）
    prev_cnt = len(old_det) - len(keep_d)
    if prev_cnt >= 10 and len(details) < prev_cnt * 0.8:
        print(f'🚨 取れた明細が前回より大きく減っています（前回 {prev_cnt}件 → 今回 {len(details)}件）。'
              f'うらかたさんの画面が途中までしか読めなかった可能性があるので、書き込まずに止めます')
        sys.exit(2)

    print(f'今回の月: 会計 {len(sales)}件（新規 {added}件）/ 明細 {len(details)}件 '
          f'/ 税抜合計 {total:,}円')
    print(f'他の月をそのまま残す: 会計 {len(keep_s)}件 / 明細 {len(keep_d)}件')
    for r in renamed: print('  名前の修正:', r)
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

    # ① 書き込む前に控えを取る（失敗しても支払方法が戻せるように）
    backup_sheet(ssid, at)

    # ①' 「消してから書く」ではなく「上書きしてから余りを空にする」。
    #    古い行数ぶん空行を足して一度に書くので、途中で切れても全消しにはならない
    def padded(new, old_n, width):
        rows = [list(r) for r in new]
        blank = [''] * width
        while len(rows) < old_n:
            rows.append(list(blank))
        return rows or [list(blank)]
    api(f'https://sheets.googleapis.com/v4/spreadsheets/{ssid}/values:batchUpdate', at, 'POST',
        {'valueInputOption': 'RAW',
         'data': [{'range': "'会計'!A2", 'values': padded(allsales, len(old_sales), 11)},
                  {'range': "'明細'!A2", 'values': padded(alldet,   len(old_det),   13)},
                  {'range': "'入金'!A2", 'values': padded(allpay,   len(old_pay),   8)}]})
    if gone:
        print(f'うらかたさんから消えた会計 {len(gone)}件を、こちらからも消しました'
              + (f'（入金 {dropped}件も一緒に）' if dropped else ''))
    print(f'書き込みました 会計{len(allsales)}件 / 明細{len(alldet)}件: '
          'https://docs.google.com/spreadsheets/d/' + ssid + '/edit')
    # 要確認でLINEは飛ばさない（2026-09-19 彩さん「この通知不要」）。
    # 画面の支払入力に「要確認」として出てくるので、そこで直す

if __name__ == '__main__':
    main()
