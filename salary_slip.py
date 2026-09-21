#!/usr/bin/env python3
"""スタッフの月次報酬明細をPDFで出す。

  python3 salary_slip.py 2026-08 中田有加 [--extra 2026-08-06:1200:プラペン研修2時間（600円×2）]

売上日報のウェブアプリ（getSalary / getIncentive）とタイムカードから材料を取り、
何に対していくら出ているかを1行ずつ並べる。出力は iCloud の 業務委託／報酬明細。
--extra は、システムにまだ入っていない特別日当を手で足すとき用（無ければ不要）。
"""
import json, os, sys, urllib.request, urllib.parse, collections, datetime, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMECARD_ID = '1gXmNha2fizWQsn7Y64kaWhwxitpt-g6mDGfdFGTl2So'


def api_url():
    s = (HERE / 'index.html').read_text(encoding='utf-8')
    return re.search(r"https://script\.google\.com/macros/s/[^']+", s).group(0)


def app(action, **params):
    q = urllib.parse.urlencode(dict(params, action=action, pin=os.environ.get('BEMOLLE_PIN', '')))
    return json.load(urllib.request.urlopen(api_url() + '?' + q))['data']


def gtoken():
    t = json.load(open(os.path.expanduser('~/.google_drive_token.json')))
    d = urllib.parse.urlencode({'client_id': t['client_id'], 'client_secret': t['client_secret'],
                                'refresh_token': t['refresh_token'], 'grant_type': 'refresh_token'}).encode()
    return json.load(urllib.request.urlopen('https://oauth2.googleapis.com/token', d))['access_token']


def timecard(staff, month):
    at = gtoken()
    u = (f'https://sheets.googleapis.com/v4/spreadsheets/{TIMECARD_ID}/values/'
         + urllib.parse.quote(f"'{staff}_{month}'!A1:D40"))
    v = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'Authorization': 'Bearer ' + at}))).get('values', [])
    out = []
    for r in v[1:]:
        r = (r + [''] * 4)[:4]
        amt = int(re.sub(r'[^\d]', '', str(r[3])) or 0)
        if r[0] and amt:
            out.append({'date': str(r[0])[:10], 'in': r[1], 'out': r[2], 'amount': amt})
    return out


def yen(n):
    return f'¥{int(n):,}'


def md(d):
    return f'{int(d[5:7])}/{int(d[8:10])}'


def kind_of(label):
    if '物販10%' in label: return '物販'
    if '定期便' in label: return '定期便'
    if '%）' in label: return '契約'
    return '施術'


def build_html(staff, month, sal, inc, tc, extras):
    y, m = month.split('-')
    detail = sorted(inc['detail'], key=lambda d: (d['date'], kind_of(d['label'])))
    by_day = collections.OrderedDict()
    for d in detail:
        by_day.setdefault(d['date'], []).append(d)

    # 施術の件数（種類別）
    treat_cnt = collections.Counter()
    for d in detail:
        if kind_of(d['label']) == '施術' and d['amount'] > 0:
            k = d['label'].split('（')[0]
            treat_cnt[k] += 1

    daily_total = sum(t['amount'] for t in tc)
    extra_total = sum(e['amount'] for e in extras)
    grand = daily_total + extra_total + inc['total']

    rows = []
    for day, ds in by_day.items():
        sub = sum(d['amount'] for d in ds)
        rows.append(f'<tr class="day"><td colspan="4">{md(day)}</td><td class="n">{yen(sub)}</td></tr>')
        for d in ds:
            k = kind_of(d['label'])
            # 「内容」は品名＋（計算の根拠）。品名が根拠に含まれていれば根拠だけにして重ならないようにする
            name, label = d.get('name', ''), d['label']
            note = label if label.startswith(name) else f'{name}　{label}'
            if k == '施術':
                note = f'{name}<span class="mini">　{label}</span>'
            elif '（' in note:
                head, tail = note.split('（', 1)
                note = f'{head}<span class="mini">（{tail}</span>'
            rows.append(f'<tr><td></td><td class="k {k}">{k}</td><td>{d.get("customer","")}</td>'
                        f'<td>{note}</td>'
                        f'<td class="n">{yen(d["amount"]) if d["amount"] else "—"}</td></tr>')
    tc_rows = ''.join(f'<tr><td>{md(t["date"])}</td><td>{t["in"]}〜{t["out"]}</td><td class="n">{yen(t["amount"])}</td></tr>' for t in tc)
    ex_rows = ''.join(f'<tr><td>{md(e["date"])}</td><td>{e["memo"]}</td><td class="n">{yen(e["amount"])}</td></tr>' for e in extras)
    today = datetime.date.today().strftime('%Y年%-m月%-d日')

    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>
@page{{size:A4;margin:16mm 14mm}}
body{{font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;color:#2b2b2b;font-size:11.5px;line-height:1.5}}
h1{{font-size:18px;margin:0 0 2px}} .sub{{color:#777;font-size:11px;margin-bottom:14px}}
h2{{font-size:13px;margin:16px 0 6px;padding-left:8px;border-left:4px solid #b07a80}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:4px 6px;border-bottom:1px solid #e4dcd6;vertical-align:top}}
th{{text-align:left;font-weight:600;color:#7a6a64;font-size:10.5px;background:#faf6f3}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
tr.day td{{background:#f6efe9;font-weight:700;border-bottom:1px solid #d9cfc8}}
.k{{font-size:10px;color:#fff;border-radius:3px;padding:1px 6px;white-space:nowrap}}
.施術{{background:#5b8c6e}} .契約{{background:#b99a66}} .物販{{background:#b07a80}} .定期便{{background:#7e93b8}}
.mini{{color:#888;font-size:10px}}
.total td{{font-size:14px;font-weight:700;background:#f6efe9;border-top:2px solid #b07a80}}
.box{{display:flex;gap:12px}} .box>div{{flex:1}}
</style></head><body>
<h1>報酬明細　{y}年{int(m)}月分</h1>
<div class="sub">{staff} 様　／　株式会社紫妃彩　Beauty Salon Bemolle　／　発行日 {today}</div>

<h2>合計</h2>
<table>
<tr><td>日当（出勤 {len(tc)}日 × ¥5,000）</td><td class="n">{yen(daily_total)}</td></tr>
{''.join(f'<tr><td>特別日当（{md(e["date"])} {e["memo"]}）</td><td class="n">{yen(e["amount"])}</td></tr>' for e in extras)}
<tr><td>インセンティブ</td><td class="n">{yen(inc['total'])}</td></tr>
<tr class="total"><td>お支払い合計</td><td class="n">{yen(grand)}</td></tr>
</table>

<h2>インセンティブの内訳</h2>
<div class="box">
<div><table>
<tr><th>区分</th><th class="n">金額</th></tr>
<tr><td>施術（件数 × 単価）</td><td class="n">{yen(inc['treat'])}</td></tr>
<tr><td>契約（月内の件数で 5%→8%→10%）</td><td class="n">{yen(inc['contract'])}</td></tr>
<tr><td>物販（10%）</td><td class="n">{yen(inc['product'])}</td></tr>
<tr><td>定期便（5%）</td><td class="n">{yen(inc['subscribe'])}</td></tr>
<tr class="total"><td>合計</td><td class="n">{yen(inc['total'])}</td></tr>
</table></div>
<div><table>
<tr><th>施術の件数</th><th class="n">件</th><th class="n">単価</th></tr>
{''.join(f'<tr><td>{k}</td><td class="n">{v}</td><td class="n">{yen({"全身":3000,"半身":2250,"セルマン":2250,"プラペン":1800,"部位":500}.get(k,0))}</td></tr>' for k,v in treat_cnt.most_common())}
</table></div>
</div>

<h2>日ごとの明細</h2>
<table>
<tr><th style="width:44px">日付</th><th style="width:52px">区分</th><th style="width:90px">お客様</th><th>内容</th><th class="n">金額</th></tr>
{''.join(rows)}
</table>

<div class="box" style="margin-top:14px">
<div><h2>出勤（日当）</h2><table><tr><th>日付</th><th>時間</th><th class="n">日当</th></tr>{tc_rows}</table></div>
<div>{'<h2>特別日当</h2><table><tr><th>日付</th><th>内容</th><th class="n">金額</th></tr>'+ex_rows+'</table>' if extras else ''}</div>
</div>
</body></html>"""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    month = args[0] if args else datetime.date.today().strftime('%Y-%m')
    staff = args[1] if len(args) > 1 else '中田有加'
    extras = []
    if '--extra' in sys.argv:
        for spec in sys.argv[sys.argv.index('--extra') + 1:]:
            if spec.startswith('--'): break
            d, a, memo = spec.split(':', 2)
            extras.append({'date': d, 'amount': int(a), 'memo': memo})

    sal = app('getSalary', month=month)
    inc = [x for x in app('getIncentive', month=month)['staff'] if x['staff'] == staff][0]
    # システムに入っている特別日当
    for a in sal.get('allowances', []):
        if a.get('staff') == staff:
            extras.append({'date': a['date'], 'amount': int(a['amount']), 'memo': a.get('memo') or a.get('reason', '')})
    tc = timecard(staff, month)

    html = build_html(staff, month, sal, inc, tc, extras)
    # 出力先は iCloud の「業務委託／報酬明細」（有加報酬.numbers と同じ場所・iPadからも見える）。
    # 毎月ここに溜めていく（2026-09-21 彩さん「どこかのフォルダに入れていってほしい」）
    out_dir = (Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/紫妃彩/Bemolle/スタッフ/業務委託/報酬明細')
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f'{staff.replace("中田","")}さん_{month[:4]}年{int(month[5:])}月_報酬明細.pdf'
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(html, wait_until='load')
        pg.pdf(path=str(out), format='A4', print_background=True)
        b.close()
    total = sum(t['amount'] for t in tc) + sum(e['amount'] for e in extras) + inc['total']
    print(f'作成: {out}')
    print(f'  日当 {sum(t["amount"] for t in tc):,} + 特別日当 {sum(e["amount"] for e in extras):,} '
          f'+ インセンティブ {inc["total"]:,} = {total:,}円（明細 {len(inc["detail"])}行）')


if __name__ == '__main__':
    main()
