#!/usr/bin/env python3
"""ベモーレ売上日報システムのスプレッドシートを作る（初回のみ実行）。
使い方: python3 setup_sheet.py            … 新規作成してIDを sheet_id.txt に保存
       python3 setup_sheet.py <既存ID>   … 既存シートに構造だけ入れ直す
"""
import json, sys, urllib.request, urllib.parse, os

TOKEN = os.path.expanduser('~/.google_drive_token.json')
HERE = os.path.dirname(os.path.abspath(__file__))

def access_token():
    t = json.load(open(TOKEN))
    d = urllib.parse.urlencode({'client_id': t['client_id'], 'client_secret': t['client_secret'],
                                'refresh_token': t['refresh_token'], 'grant_type': 'refresh_token'}).encode()
    return json.load(urllib.request.urlopen('https://oauth2.googleapis.com/token', d))['access_token']

def api(url, at, method='GET', body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Authorization': 'Bearer ' + at,
                                          'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req))

SHEETS = {
    '会計':      ['会計ID','日付','顧客名','担当者','アポインター','メモ','税抜合計','税込合計','支払状態','作成日時','更新日時'],
    '明細':      ['明細ID','会計ID','日付','種別','名称','数量','区分','税率','税抜金額','税込金額','担当者','初回','備考'],
    '入金':      ['入金ID','会計ID','会計日','支払方法','金額','状態','入金日','メモ'],
    '在庫払出':  ['払出ID','日付','商品名','数量','用途','金額','メモ','登録日時'],
    '商品マスタ': ['商品名','税率','税抜単価','仕入値','ブランド','表示順','有効'],
    'メニューマスタ': ['メニュー名','区分','表示順','有効'],
    'スタッフ':  ['氏名','インセンティブ対象','表示順','有効'],
    '設定':      ['キー','値'],
    'アーカイブ': ['削除日時','シート','内容'],
}

MENUS = [['全身','全身',1,True],['下半身','半身',2,True],['上半身','半身',3,True],
         ['セルマン','セルマン',4,True],['プラペン','プラペン',5,True],['幹細胞','プラペン',6,True],
         ['部位','部位',7,True],['ラジショット','対象外',8,True],
         ['全身体験','全身',9,True],['下半身体験','半身',10,True],['プラペン幹細胞体験','プラペン',11,True]]

def main():
    at = access_token()
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    if not sid:
        body = {'properties': {'title': 'ベモーレ売上日報', 'locale': 'ja_JP', 'timeZone': 'Asia/Tokyo'},
                'sheets': [{'properties': {'title': n}} for n in SHEETS]}
        r = api('https://sheets.googleapis.com/v4/spreadsheets', at, 'POST', body)
        sid = r['spreadsheetId']
        open(os.path.join(HERE, 'sheet_id.txt'), 'w').write(sid)
        print('作成しました:', r['spreadsheetUrl'])

    data = [{'range': f"'{name}'!A1", 'values': [cols]} for name, cols in SHEETS.items()]

    prods = json.load(open(os.path.join(HERE, 'products.json'), encoding='utf-8'))
    rows = [[p['名称'], p['税率'], p['単価'], p.get('仕入', ''), p.get('ブランド', ''), i + 1, True]
            for i, p in enumerate(prods['商品'])]
    rows.append(['ボンバー', 8, 8000, '', 'H.R.', len(rows) + 1, True])   # 棚卸し未掲載（在庫0）
    data.append({'range': "'商品マスタ'!A2", 'values': rows})
    data.append({'range': "'メニューマスタ'!A2", 'values': MENUS})
    data.append({'range': "'設定'!A2", 'values': [
        ['定期便の判定', '日付が1日 かつ 金額＝定価×数量×0.9'],
        ['定期便インセンティブ', '税抜の5%（お客様ごと・1日ごとに合算してから計算）'],
        ['物販インセンティブ', '税抜の10%'],
        ['契約インセンティブ', '月内1〜2件目5% / 3〜4件目8% / 5件目以降10%（端数切捨）'],
        ['ラジショット・部位チケット', '5%固定・契約の件数に数えない'],
        ['施術の定額', '全身3,000(1日3件) 半身2,250(4件) セルマン2,250(4件) プラペン1,800(5件) 部位500'],
        ['担当者が空の明細', 'インセンティブ対象外（誰にも付けない）'],
        ['日付', '決済日で入れる（出勤していない日にも行が立つ）'],
    ]})

    api(f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values:batchUpdate', at, 'POST',
        {'valueInputOption': 'RAW', 'data': data})

    meta = api(f'https://sheets.googleapis.com/v4/spreadsheets/{sid}?fields=sheets.properties', at)
    reqs = []
    for s in meta['sheets']:
        gid = s['properties']['sheetId']
        reqs += [{'repeatCell': {'range': {'sheetId': gid, 'startRowIndex': 0, 'endRowIndex': 1},
                                 'cell': {'userEnteredFormat': {'textFormat': {'bold': True},
                                          'backgroundColor': {'red': .95, 'green': .94, 'blue': .92}}},
                                 'fields': 'userEnteredFormat(textFormat,backgroundColor)'}},
                 {'updateSheetProperties': {'properties': {'sheetId': gid, 'gridProperties': {'frozenRowCount': 1}},
                                            'fields': 'gridProperties.frozenRowCount'}}]
    api(f'https://sheets.googleapis.com/v4/spreadsheets/{sid}:batchUpdate', at, 'POST', {'requests': reqs})
    print('シートID:', sid)
    print('URL: https://docs.google.com/spreadsheets/d/' + sid + '/edit')

if __name__ == '__main__':
    main()
