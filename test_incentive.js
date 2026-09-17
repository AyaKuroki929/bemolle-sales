// 紙の日計表（2026年8月・実物）と計算結果が一致するかを検証する
const fs = require('fs'), vm = require('vm');

const ctx = {
  console,
  Utilities: {
    formatDate: (d, tz, f) => {
      const p = n => String(n).padStart(2, '0');
      const s = `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
      if (f === 'yyyy-MM') return s.slice(0, 7);
      if (f === 'yyyy-MM-dd') return s.slice(0, 10);
      if (f === 'yyyyMMddHHmmss') return s.replace(/[-: ]/g, '');
      return s;
    },
    getUuid: () => 'uuid'
  },
  SpreadsheetApp: { getActiveSpreadsheet: () => ({ getSheetByName: () => null, insertSheet: () => ({}) }) },
  PropertiesService: { getScriptProperties: () => ({ getProperty: () => null, setProperty(){}, deleteProperty(){} }) },
  LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock(){} }) },
  ContentService: { createTextOutput: () => ({ setMimeType: () => ({}) }), MimeType: { JSON: 'json' } },
  ScriptApp: { getProjectTriggers: () => [] },
  Session: { getScriptTimeZone: () => 'Asia/Tokyo' }
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('Code.gs', 'utf8'), ctx);

// ── 紙から起こした8月の実データ（担当=中田有加の行）──────────────
const S = [], I = [], P = [];
let n = 0;
function sale(date, customer, staff, items, appointer) {
  const id = 'S' + (++n);
  S.push({ '会計ID': id, '日付': date, '顧客名': customer, '担当者': staff, 'アポインター': appointer || '' });
  items.forEach((it, k) => I.push({
    '明細ID': id + '-' + k, '会計ID': id, '日付': date, '種別': it.t, '名称': it.n,
    '数量': it.q || 1, '区分': it.k || '対象外', '税率': it.tax || 10,
    '税抜金額': it.net || 0, '税込金額': Math.round((it.net||0) * (1 + (it.tax||10)/100)),
    '担当者': staff, '初回': !!it.first, '備考': ''
  }));
}
const Y = '中田有加';
// 8/15 ①桑原様 全身12回(-5%) 287,280 → 1件目 5% = 14,364 ＋全身3,000
sale('2026-08-05', '桑原様', Y, [{t:'施術',n:'全身',k:'全身'}, {t:'契約',n:'全身12回',k:'通常契約',net:287280}]);
// 8/18 ②村山様 プラペン6回 198,000 → 2件目 5% = 9,900 ＋全身3,000
sale('2026-08-08', '村山様', Y, [{t:'施術',n:'全身',k:'全身'}, {t:'契約',n:'プラペン6回',k:'通常契約',net:198000}]);
// 8/17 ③堀池様 全身12回 302,400 → 3件目 8% = 24,192 ＋全身3,000
sale('2026-08-17', '堀池様', Y, [{t:'施術',n:'全身',k:'全身'}, {t:'契約',n:'全身12回',k:'通常契約',net:302400}]);
// 8/19 ④村山様 全身6回 151,620 → 4件目 8% = 12,129
sale('2026-08-19', '村山様', Y, [{t:'契約',n:'全身6回',k:'通常契約',net:151620}]);
// 8/20 ⑤大寺様 全身12回 287,280 → 5件目 10% = 28,728
sale('2026-08-20', '大寺様', Y, [{t:'契約',n:'全身12回',k:'通常契約',net:287280}]);
// 8/24 ⑥大寺様 全身12回 302,400 → 6件目 10% = 30,240 ＋全身3,000 ＋物販105,600の10%=10,560
sale('2026-08-24', '大寺様', Y, [
  {t:'施術',n:'全身',k:'全身'},
  {t:'契約',n:'全身12回',k:'通常契約',net:302400},
  {t:'その他',n:'その他',net:9000},
  {t:'物販',n:'サプリ一式・コーヒー',k:'物販',net:43600,tax:8},
  {t:'物販',n:'下着一式',k:'物販',net:62000,tax:10}]);
// 8/21 長原様・倉岡様 全身×2 ＋ 倉岡様物販7,700(8%)→770
sale('2026-08-21', '長原様', Y, [{t:'施術',n:'全身',k:'全身'}]);
sale('2026-08-21', '倉岡様', Y, [{t:'施術',n:'全身',k:'全身'}, {t:'物販',n:'HRプロテイン黒蜜',k:'物販',net:7700,tax:8}]);
// 上限テスト：同じ日に全身4件（上限3件）→ 3件分しか付かない
['A','B','C','D'].forEach(c => sale('2026-08-26', c+'様', Y, [{t:'施術',n:'全身',k:'全身'}]));
// ラジショット契約（件数に数えず5%固定）
sale('2026-08-27', '長原様', Y, [{t:'契約',n:'ラジショット6回',k:'ラジショット',net:100000}]);
// 折半：クローザー中田・アポインター黒木 → 中田は半額
sale('2026-08-28', '折半様', Y, [{t:'施術',n:'全身',k:'全身'}], '黒木彩');
// 定期便：初回は対象外・2ヶ月目以降は5%
sale('2026-08-29', '定期様', Y, [{t:'定期便',n:'コーヒー',k:'定期便',net:10000,first:true},
                                {t:'定期便',n:'ベーシック',k:'定期便',net:20000}]);

ctx.loadAll_ = () => ({ sales: S, items: I, payments: P });
ctx.getMasters = () => ({ products: [], menus: [], staff: [{ name: Y, incentive: true }, { name: '黒木彩', incentive: false }] });

const r = ctx.getIncentive('2026-08').staff.find(s => s.staff === Y);

const expect = [
  ['契約 1件目 5%（8/5 桑原様287,280）', 14364],
  ['契約 2件目 5%（8/8 村山様198,000）', 9900],
  ['契約 3件目 8%（堀池様302,400）', 24192],
  ['契約 4件目 8%（村山様151,620・端数切捨）', 12129],
  ['契約 5件目 10%（大寺様287,280）', 28728],
  ['契約 6件目 10%（大寺様302,400）', 30240],
  ['ラジショット 5%固定（100,000）', 5000]
];
const contractDetail = r.detail.filter(d => /件目|ラジショット/.test(d.label));
let ng = 0;
console.log('■ 契約インセンティブ（紙の余白の数字と照合）');
expect.forEach((e, i) => {
  const got = contractDetail[i] ? contractDetail[i].amount : null;
  const okk = got === e[1];
  if (!okk) ng++;
  console.log(`  ${okk ? '✅' : '❌'} ${e[0]} → 期待 ${e[1].toLocaleString()} / 計算 ${got == null ? 'なし' : got.toLocaleString()}`);
});

console.log('\n■ その他の検証');
const checks = [
  ['契約合計', r.contract, 14364+9900+24192+12129+28728+30240+5000],
  ['物販10%（105,600＋7,700=113,300 → 11,330）', r.product, 11330],
  ['定期便5%（初回除く20,000 → 1,000）', r.subscribe, 1000],
  ['施術（全身 6件 ＋ 上限内3件 ＋ 折半0.5件）',
   r.treat, 3000*6 + 3000*3 + 1500]
];
checks.forEach(c => {
  const okk = c[1] === c[2];
  if (!okk) ng++;
  console.log(`  ${okk ? '✅' : '❌'} ${c[0]} → 期待 ${c[2].toLocaleString()} / 計算 ${c[1].toLocaleString()}`);
});
console.log(`\n  1日上限の確認（8/26に全身4件）: ${r.detail.filter(d=>d.date==='2026-08-26'&&d.amount>0).length}件分だけ加算 ＋ 上限超 ${r.detail.filter(d=>/上限超/.test(d.label)).length}件`);
console.log(`\n合計（日当は別）: ${r.total.toLocaleString()}円`);
console.log(ng === 0 ? '\n🎉 全項目 一致' : `\n⚠️ ${ng}件 不一致`);
process.exit(ng === 0 ? 0 : 1);
