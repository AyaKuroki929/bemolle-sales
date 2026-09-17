// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Bemolle 売上日報システム — Google Apps Script バックエンド
//
//  紙の「日計表」を置き換える。1会計=1レコードで入力し、
//  税率別集計・支払方法別集計・未収管理・インセンティブ計算を自動化する。
//
//  セットアップ:
//  1. Googleスプレッドシートを新規作成（名前: ベモーレ売上日報）
//  2. 拡張機能 → Apps Script
//  3. Code.gs にこのファイル、index.html を追加して貼り付け
//  4. 実行 → initSheets（初回のみ）
//  5. デプロイ → ウェブアプリ（実行: 自分 / アクセス: 全員）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const SH_SALES    = '会計';
const SH_ITEMS    = '明細';
const SH_PAYMENTS = '入金';
const SH_STOCK    = '在庫払出';
const SH_PRODUCTS = '商品マスタ';
const SH_MENUS    = 'メニューマスタ';
const SH_STAFF    = 'スタッフ';
const SH_SETTINGS = '設定';
const SH_ARCHIVE  = 'アーカイブ';

// ── 報酬規定（2025-04-03版・PDF準拠。変更時はここだけ直す）──────────
// 施術インセンティブ: 単価と「1日あたりの上限件数」
// ※率で計算する分（契約・物販・定期便）の端数は切り捨て（紙の運用に合わせた）
const TREAT_RULES = {
  '全身':     { amount: 3000, dailyMax: 3 },
  '半身':     { amount: 2250, dailyMax: 4 },
  'セルマン': { amount: 2250, dailyMax: 4 },
  'プラペン': { amount: 1800, dailyMax: 5 },
  '部位':     { amount: 500,  dailyMax: 99 }  // 1部位あたり
};
const RATE_PRODUCT   = 0.10;  // 物販 10%
const RATE_SUBSCRIBE = 0.05;  // 定期便 2ヶ月目以降 5%
const RATE_FIXED5    = 0.05;  // ラジショット・部位チケット（件数に数えない契約）5%
// 契約インセンティブ: 月内の件数に応じて 1〜2件目5% / 3〜4件目8% / 5件目以降10%
function contractRate_(indexFromOne) {
  if (indexFromOne <= 2) return 0.05;
  if (indexFromOne <= 4) return 0.08;
  return 0.10;
}
// 件数に数えない契約の区分
const NO_COUNT_CONTRACTS = ['ラジショット', '部位チケット'];

const PAY_METHODS = ['現金', 'JMS', 'Square', '振込', 'HPポイント', 'その他'];
const STOCK_USES  = ['サロン使用', '黒木購入'];

// ─── エントリポイント ───────────────────────────────
function doGet(e)  { return handle(e.parameter, null); }
function doPost(e) {
  const body = e.postData ? JSON.parse(e.postData.contents) : {};
  return handle(e.parameter, body);
}

// 管理者PINが要るアクション（マスタ変更・削除・設定）
const ADMIN_ACTIONS = ['init', 'deleteSale', 'deleteStock', 'saveMaster', 'deleteMaster',
                       'changePin', 'setupTriggers'];

function getStoredPin() {
  const p = PropertiesService.getScriptProperties().getProperty('ADMIN_PIN');
  return p || '1234';
}
function pinRateGuard_(pin) {
  const props = PropertiesService.getScriptProperties();
  const fails = Number(props.getProperty('PIN_FAILS') || 0);
  const until = Number(props.getProperty('PIN_LOCK_UNTIL') || 0);
  if (until && Date.now() < until) return false;
  if (pin === getStoredPin()) {
    props.deleteProperty('PIN_FAILS'); props.deleteProperty('PIN_LOCK_UNTIL');
    return true;
  }
  const n = fails + 1;
  props.setProperty('PIN_FAILS', String(n));
  if (n >= 5) props.setProperty('PIN_LOCK_UNTIL', String(Date.now() + 10 * 60 * 1000));
  return false;
}

function handle(params, body) {
  const d = body || {};
  const action = params.action || d.action;
  try {
    if (ADMIN_ACTIONS.indexOf(action) !== -1) {
      const pin = ((d.pin != null ? d.pin : params.pin) || '').toString();
      if (!pinRateGuard_(pin)) throw new Error('unauthorized');
    }
    let result;
    switch (action) {
      case 'init':            result = initSheets();               break;
      case 'getStartupData':  result = getStartupData();           break;
      case 'saveSale':        result = saveSale(d);                break;
      case 'getSales':        result = getSales(params);           break;
      case 'getSale':         result = getSale(params.id || d.id); break;
      case 'deleteSale':      result = deleteSale(d);              break;
      case 'settlePayment':   result = settlePayment(d);           break;
      case 'getUnpaid':       result = getUnpaid();                break;
      case 'saveStock':       result = saveStock(d);               break;
      case 'getStocks':       result = getStocks(params);          break;
      case 'deleteStock':     result = deleteStock(d);             break;
      case 'getMasters':      result = getMasters();               break;
      case 'saveMaster':      result = saveMaster(d);              break;
      case 'deleteMaster':    result = deleteMaster(d);            break;
      case 'getSummary':      result = getSummary(params.month);   break;
      case 'getIncentive':    result = getIncentive(params.month); break;
      case 'exportCsv':       result = exportCsv(params.month);    break;
      case 'checkPin':        result = { ok: (d.pin || '') === getStoredPin() }; break;
      case 'changePin':       result = changePin(d);               break;
      case 'keepWarm':        result = { ok: true };               break;
      default: throw new Error('Unknown action: ' + action);
    }
    return ok(result);
  } catch (err) {
    return err_(err.message);
  }
}
function ok(data)  { return json({ ok: true,  data: data }); }
function err_(msg) { return json({ ok: false, error: msg }); }
function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
function sh(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(name) || ss.insertSheet(name);
}
function withLock_(fn) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) throw new Error('混み合っています。もう一度お試しください');
  try { return fn(); } finally { lock.releaseLock(); }
}
function newId_(prefix) {
  return prefix + Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyyMMddHHmmss')
       + Math.floor(Math.random() * 900 + 100);
}
function ymd_(v) {
  if (!v) return '';
  if (Object.prototype.toString.call(v) === '[object Date]') {
    return Utilities.formatDate(v, 'Asia/Tokyo', 'yyyy-MM-dd');
  }
  return String(v).slice(0, 10);
}
function nowStr_() {
  return Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss');
}

// ─── シート初期化 ──────────────────────────────────
function initSheets() {
  const defs = [
    [SH_SALES,    ['会計ID','日付','顧客名','担当者','アポインター','メモ','税抜合計','税込合計','作成日時','更新日時']],
    [SH_ITEMS,    ['明細ID','会計ID','日付','種別','名称','数量','区分','税率','税抜金額','税込金額','担当者','初回','備考']],
    [SH_PAYMENTS, ['入金ID','会計ID','会計日','支払方法','金額','状態','入金日','メモ']],
    [SH_STOCK,    ['払出ID','日付','商品名','数量','用途','金額','メモ','登録日時']],
    [SH_PRODUCTS, ['商品名','税率','税抜単価','表示順','有効']],
    [SH_MENUS,    ['メニュー名','区分','表示順','有効']],
    [SH_STAFF,    ['氏名','インセンティブ対象','表示順','有効']],
    [SH_SETTINGS, ['キー','値']],
    [SH_ARCHIVE,  ['削除日時','シート','内容']]
  ];
  defs.forEach(function (def) {
    const s = sh(def[0]);
    if (s.getLastRow() === 0) {
      s.appendRow(def[1]);
      s.getRange(1, 1, 1, def[1].length).setFontWeight('bold').setBackground('#f3f0ea');
      s.setFrozenRows(1);
    }
  });
  // 初期マスタ（空のときだけ）
  const menus = sh(SH_MENUS);
  if (menus.getLastRow() <= 1) {
    [['全身','全身',1,true],['半身','半身',2,true],['下半身','半身',3,true],['上半身','半身',4,true],
     ['セルマン','セルマン',5,true],['プラペン','プラペン',6,true],['部位','部位',7,true],
     ['ラジショット','対象外',8,true],['体験','対象外',9,true],['フェイシャル','対象外',10,true]]
      .forEach(function (r) { menus.appendRow(r); });
  }
  const staff = sh(SH_STAFF);
  if (staff.getLastRow() <= 1) {
    [['中田有加', true, 1, true], ['黒木彩', false, 2, true]]
      .forEach(function (r) { staff.appendRow(r); });
  }
  return { ok: true };
}

function getStartupData() {
  return {
    masters: getMasters(),
    payMethods: PAY_METHODS,
    stockUses: STOCK_USES,
    today: Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd'),
    month: Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM')
  };
}

// ─── マスタ ────────────────────────────────────────
function readSheet_(name) {
  const s = sh(name);
  const last = s.getLastRow();
  if (last <= 1) return [];
  const vals = s.getRange(2, 1, last - 1, s.getLastColumn()).getValues();
  const head = s.getRange(1, 1, 1, s.getLastColumn()).getValues()[0];
  return vals.map(function (row) {
    const o = {};
    head.forEach(function (h, i) { o[h] = row[i]; });
    return o;
  });
}

function getMasters() {
  const act = function (r) { return r['有効'] !== false && r['有効'] !== 'FALSE'; };
  const byOrder = function (a, b) { return (Number(a['表示順']) || 0) - (Number(b['表示順']) || 0); };
  return {
    products: readSheet_(SH_PRODUCTS).filter(act).sort(byOrder).map(function (r) {
      return { name: r['商品名'], tax: Number(r['税率']) || 10, price: Number(r['税抜単価']) || 0 };
    }),
    menus: readSheet_(SH_MENUS).filter(act).sort(byOrder).map(function (r) {
      return { name: r['メニュー名'], kind: r['区分'] || '対象外' };
    }),
    staff: readSheet_(SH_STAFF).filter(act).sort(byOrder).map(function (r) {
      return { name: r['氏名'], incentive: (r['インセンティブ対象'] === true || r['インセンティブ対象'] === 'TRUE') };
    })
  };
}

function saveMaster(d) {
  return withLock_(function () {
    const map = { product: SH_PRODUCTS, menu: SH_MENUS, staff: SH_STAFF };
    const name = map[d.type];
    if (!name) throw new Error('種類が不正です');
    const s = sh(name);
    const keyCol = 1;
    const rows = s.getLastRow() > 1 ? s.getRange(2, 1, s.getLastRow() - 1, s.getLastColumn()).getValues() : [];
    let line;
    if (d.type === 'product') line = [d.name, Number(d.tax) || 10, Number(d.price) || 0, Number(d.order) || 99, true];
    if (d.type === 'menu')    line = [d.name, d.kind || '対象外', Number(d.order) || 99, true];
    if (d.type === 'staff')   line = [d.name, !!d.incentive, Number(d.order) || 99, true];
    for (let i = 0; i < rows.length; i++) {
      if (String(rows[i][keyCol - 1]) === String(d.originalName || d.name)) {
        s.getRange(i + 2, 1, 1, line.length).setValues([line]);
        return { updated: true };
      }
    }
    s.appendRow(line);
    return { created: true };
  });
}

function deleteMaster(d) {
  return withLock_(function () {
    const map = { product: SH_PRODUCTS, menu: SH_MENUS, staff: SH_STAFF };
    const s = sh(map[d.type]);
    const rows = s.getLastRow() > 1 ? s.getRange(2, 1, s.getLastRow() - 1, s.getLastColumn()).getValues() : [];
    for (let i = 0; i < rows.length; i++) {
      if (String(rows[i][0]) === String(d.name)) {
        // 履歴を壊さないよう「有効=false」にするだけ
        s.getRange(i + 2, s.getLastColumn()).setValue(false);
        return { disabled: true };
      }
    }
    throw new Error('見つかりません');
  });
}

function changePin(d) {
  const np = String(d.newPin || '');
  if (!/^\d{4,8}$/.test(np)) throw new Error('PINは4〜8桁の数字');
  PropertiesService.getScriptProperties().setProperty('ADMIN_PIN', np);
  return { ok: true };
}

// ─── 会計（売上）────────────────────────────────────
function grossOf_(net, taxRate) {
  return Math.round(Number(net || 0) * (1 + (Number(taxRate) || 0) / 100));
}
function deleteRowsByKey_(sheetName, keyColIdx, keyValue) {
  const s = sh(sheetName);
  const last = s.getLastRow();
  if (last <= 1) return;
  const vals = s.getRange(2, keyColIdx, last - 1, 1).getValues();
  for (let i = vals.length - 1; i >= 0; i--) {
    if (String(vals[i][0]) === String(keyValue)) s.deleteRow(i + 2);
  }
}

/**
 * 会計を保存する（新規・上書きの両対応）。
 * 過去日でも日付を指定すればそのまま登録・修正できる。
 */
function saveSale(d) {
  return withLock_(function () {
    const date = ymd_(d.date);
    if (!date) throw new Error('日付を入れてください');
    if (!d.staff) throw new Error('担当者を選んでください');
    const items    = (d.items || []).filter(function (it) { return it && it.name; });
    const payments = (d.payments || []).filter(function (p) { return p && Number(p.amount); });
    if (!items.length) throw new Error('施術か商品を1つ以上入れてください');

    const id = d.id || newId_('S');
    const isUpdate = !!d.id;

    let netTotal = 0, grossTotal = 0;
    const itemRows = items.map(function (it) {
      const tax = (it.tax === 0 || it.tax) ? Number(it.tax) : 10;
      const net = Number(it.net || 0);
      const gross = grossOf_(net, tax);
      netTotal += net; grossTotal += gross;
      return [newId_('I'), id, date, it.type || '施術', it.name, Number(it.qty || 1),
              it.kind || '対象外', tax, net, gross, it.staff || d.staff,
              it.first === true, it.note || ''];
    });

    const payRows = payments.map(function (p) {
      const status = p.status === '未収' ? '未収' : '入金済';
      return [newId_('P'), id, date, p.method || '現金', Number(p.amount || 0),
              status, status === '入金済' ? (ymd_(p.paidDate) || date) : '', p.memo || ''];
    });

    // 会計ヘッダ
    const s = sh(SH_SALES);
    const row = [id, date, d.customer || '', d.staff, d.appointer || '', d.memo || '',
                 netTotal, grossTotal, isUpdate ? (d.createdAt || nowStr_()) : nowStr_(), nowStr_()];
    if (isUpdate) {
      const last = s.getLastRow();
      const ids = last > 1 ? s.getRange(2, 1, last - 1, 1).getValues() : [];
      let found = -1;
      for (let i = 0; i < ids.length; i++) if (String(ids[i][0]) === String(id)) { found = i + 2; break; }
      if (found < 0) throw new Error('会計が見つかりません');
      row[8] = s.getRange(found, 9).getValue() || nowStr_();
      s.getRange(found, 1, 1, row.length).setValues([row]);
      deleteRowsByKey_(SH_ITEMS, 2, id);
      deleteRowsByKey_(SH_PAYMENTS, 2, id);
    } else {
      s.appendRow(row);
    }
    if (itemRows.length) {
      sh(SH_ITEMS).getRange(sh(SH_ITEMS).getLastRow() + 1, 1, itemRows.length, itemRows[0].length)
        .setValues(itemRows);
    }
    if (payRows.length) {
      sh(SH_PAYMENTS).getRange(sh(SH_PAYMENTS).getLastRow() + 1, 1, payRows.length, payRows[0].length)
        .setValues(payRows);
    }
    return { id: id, net: netTotal, gross: grossTotal, paid: payRows.length };
  });
}

function loadAll_() {
  return {
    sales: readSheet_(SH_SALES),
    items: readSheet_(SH_ITEMS),
    payments: readSheet_(SH_PAYMENTS)
  };
}

function buildSale_(head, items, payments) {
  return {
    id: head['会計ID'], date: ymd_(head['日付']), customer: head['顧客名'],
    staff: head['担当者'], appointer: head['アポインター'], memo: head['メモ'],
    net: Number(head['税抜合計']) || 0, gross: Number(head['税込合計']) || 0,
    createdAt: head['作成日時'],
    items: items.map(function (r) {
      return { id: r['明細ID'], type: r['種別'], name: r['名称'], qty: Number(r['数量']) || 1,
               kind: r['区分'], tax: Number(r['税率']) || 0, net: Number(r['税抜金額']) || 0,
               gross: Number(r['税込金額']) || 0, staff: r['担当者'],
               first: (r['初回'] === true || r['初回'] === 'TRUE'), note: r['備考'] };
    }),
    payments: payments.map(function (r) {
      return { id: r['入金ID'], method: r['支払方法'], amount: Number(r['金額']) || 0,
               status: r['状態'], paidDate: ymd_(r['入金日']), memo: r['メモ'] };
    })
  };
}

/** 日付（date=yyyy-MM-dd）か月（month=yyyy-MM）で会計を取得。過去日も自由に見られる */
function getSales(params) {
  const all = loadAll_();
  const date = params.date ? ymd_(params.date) : '';
  const month = params.month || '';
  const heads = all.sales.filter(function (r) {
    const dt = ymd_(r['日付']);
    if (date)  return dt === date;
    if (month) return dt.slice(0, 7) === month;
    return true;
  }).sort(function (a, b) { return ymd_(a['日付']) < ymd_(b['日付']) ? -1 : 1; });

  return heads.map(function (h) {
    const id = h['会計ID'];
    return buildSale_(h,
      all.items.filter(function (r) { return String(r['会計ID']) === String(id); }),
      all.payments.filter(function (r) { return String(r['会計ID']) === String(id); }));
  });
}

function getSale(id) {
  const all = loadAll_();
  const h = all.sales.filter(function (r) { return String(r['会計ID']) === String(id); })[0];
  if (!h) throw new Error('会計が見つかりません');
  return buildSale_(h,
    all.items.filter(function (r) { return String(r['会計ID']) === String(id); }),
    all.payments.filter(function (r) { return String(r['会計ID']) === String(id); }));
}

function deleteSale(d) {
  return withLock_(function () {
    const id = d.id;
    const sale = getSale(id);
    sh(SH_ARCHIVE).appendRow([nowStr_(), SH_SALES, JSON.stringify(sale)]);
    deleteRowsByKey_(SH_SALES, 1, id);
    deleteRowsByKey_(SH_ITEMS, 2, id);
    deleteRowsByKey_(SH_PAYMENTS, 2, id);
    return { deleted: true };
  });
}

// ─── 未収（後日payment）の消し込み ──────────────────────
function getUnpaid() {
  const all = loadAll_();
  return all.payments.filter(function (r) { return r['状態'] === '未収'; })
    .map(function (r) {
      const h = all.sales.filter(function (s) { return String(s['会計ID']) === String(r['会計ID']); })[0] || {};
      return { id: r['入金ID'], saleId: r['会計ID'], date: ymd_(r['会計日']),
               customer: h['顧客名'] || '', method: r['支払方法'],
               amount: Number(r['金額']) || 0, memo: r['メモ'] };
    }).sort(function (a, b) { return a.date < b.date ? -1 : 1; });
}

function settlePayment(d) {
  return withLock_(function () {
    const s = sh(SH_PAYMENTS);
    const last = s.getLastRow();
    if (last <= 1) throw new Error('入金が見つかりません');
    const vals = s.getRange(2, 1, last - 1, s.getLastColumn()).getValues();
    for (let i = 0; i < vals.length; i++) {
      if (String(vals[i][0]) === String(d.id)) {
        s.getRange(i + 2, 4).setValue(d.method || vals[i][3]); // 支払方法
        s.getRange(i + 2, 6).setValue('入金済');
        s.getRange(i + 2, 7).setValue(ymd_(d.paidDate) || ymd_(new Date()));
        return { settled: true };
      }
    }
    throw new Error('入金が見つかりません');
  });
}

// ─── 在庫払出（売上でない持ち出し）──────────────────────
function saveStock(d) {
  return withLock_(function () {
    const date = ymd_(d.date);
    if (!date) throw new Error('日付を入れてください');
    if (!d.name) throw new Error('商品を選んでください');
    if (STOCK_USES.indexOf(d.use) === -1) throw new Error('用途は サロン使用 か 黒木購入');
    const s = sh(SH_STOCK);
    const id = d.id || newId_('K');
    const row = [id, date, d.name, Number(d.qty || 1), d.use, Number(d.amount || 0), d.memo || '', nowStr_()];
    if (d.id) {
      const vals = s.getLastRow() > 1 ? s.getRange(2, 1, s.getLastRow() - 1, 1).getValues() : [];
      for (let i = 0; i < vals.length; i++) {
        if (String(vals[i][0]) === String(d.id)) {
          s.getRange(i + 2, 1, 1, row.length).setValues([row]);
          return { updated: true, id: id };
        }
      }
      throw new Error('払出が見つかりません');
    }
    s.appendRow(row);
    return { created: true, id: id };
  });
}

function getStocks(params) {
  const month = params.month || '';
  const date = params.date ? ymd_(params.date) : '';
  return readSheet_(SH_STOCK).filter(function (r) {
    const dt = ymd_(r['日付']);
    if (date) return dt === date;
    if (month) return dt.slice(0, 7) === month;
    return true;
  }).map(function (r) {
    return { id: r['払出ID'], date: ymd_(r['日付']), name: r['商品名'],
             qty: Number(r['数量']) || 0, use: r['用途'],
             amount: Number(r['金額']) || 0, memo: r['メモ'] };
  }).sort(function (a, b) { return a.date < b.date ? -1 : 1; });
}

function deleteStock(d) {
  return withLock_(function () {
    const s = sh(SH_STOCK);
    const vals = s.getLastRow() > 1 ? s.getRange(2, 1, s.getLastRow() - 1, s.getLastColumn()).getValues() : [];
    for (let i = 0; i < vals.length; i++) {
      if (String(vals[i][0]) === String(d.id)) {
        sh(SH_ARCHIVE).appendRow([nowStr_(), SH_STOCK, JSON.stringify(vals[i])]);
        s.deleteRow(i + 2);
        return { deleted: true };
      }
    }
    throw new Error('払出が見つかりません');
  });
}

// ─── 月次集計（税率別・支払方法別・未収）──────────────────
function getSummary(month) {
  if (!month) month = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM');
  const all = loadAll_();
  const inMonth = function (v) { return ymd_(v).slice(0, 7) === month; };

  const items = all.items.filter(function (r) { return inMonth(r['日付']); });
  const pays  = all.payments.filter(function (r) { return inMonth(r['会計日']); });

  const byDate = {}, byTax = {}, byType = {}, byMethod = {}, byStaff = {};
  let net = 0, gross = 0;

  items.forEach(function (r) {
    const dt = ymd_(r['日付']);
    const n = Number(r['税抜金額']) || 0, g = Number(r['税込金額']) || 0;
    const tax = String(Number(r['税率']) || 0);
    net += n; gross += g;
    if (!byDate[dt]) byDate[dt] = { net: 0, gross: 0 };
    byDate[dt].net += n; byDate[dt].gross += g;
    if (!byTax[tax]) byTax[tax] = { net: 0, gross: 0 };
    byTax[tax].net += n; byTax[tax].gross += g;
    const t = r['種別'] || 'その他';
    if (!byType[t]) byType[t] = { net: 0, gross: 0 };
    byType[t].net += n; byType[t].gross += g;
    const st = r['担当者'] || '';
    if (!byStaff[st]) byStaff[st] = { net: 0, gross: 0 };
    byStaff[st].net += n; byStaff[st].gross += g;
  });

  let unpaid = 0;
  pays.forEach(function (r) {
    const m = r['支払方法'] || 'その他';
    const a = Number(r['金額']) || 0;
    if (!byMethod[m]) byMethod[m] = { paid: 0, unpaid: 0 };
    if (r['状態'] === '未収') { byMethod[m].unpaid += a; unpaid += a; }
    else byMethod[m].paid += a;
  });

  const stocks = getStocks({ month: month });
  const stockSum = {};
  STOCK_USES.forEach(function (u) { stockSum[u] = { qty: 0, amount: 0 }; });
  stocks.forEach(function (s) {
    if (!stockSum[s.use]) stockSum[s.use] = { qty: 0, amount: 0 };
    stockSum[s.use].qty += s.qty; stockSum[s.use].amount += s.amount;
  });

  return { month: month, net: net, gross: gross, unpaid: unpaid,
           byDate: byDate, byTax: byTax, byType: byType, byMethod: byMethod,
           byStaff: byStaff, stock: stockSum, count: items.length };
}

// ─── インセンティブ自動計算（報酬規定2025-04-03準拠）─────────
function getIncentive(month) {
  if (!month) month = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM');
  const all = loadAll_();
  const inMonth = function (v) { return ymd_(v).slice(0, 7) === month; };
  const saleById = {};
  all.sales.forEach(function (s) { saleById[String(s['会計ID'])] = s; });

  const items = all.items.filter(function (r) { return inMonth(r['日付']); });
  const targets = getMasters().staff.filter(function (s) { return s.incentive; })
                    .map(function (s) { return s.name; });

  const result = {};
  const ensure = function (name) {
    if (!result[name]) {
      result[name] = { staff: name, treat: 0, contract: 0, product: 0, subscribe: 0,
                       adjust: 0, total: 0, detail: [] };
    }
    return result[name];
  };
  targets.forEach(ensure);

  // ① 施術インセンティブ（1日あたり上限件数を適用 → 折半）
  const treats = items.filter(function (r) { return r['種別'] === '施術' && TREAT_RULES[r['区分']]; });
  const groups = {};
  treats.forEach(function (r) {
    const closer = r['担当者'] || '';
    const key = closer + '|' + ymd_(r['日付']) + '|' + r['区分'];
    if (!groups[key]) groups[key] = [];
    groups[key].push(r);
  });
  Object.keys(groups).forEach(function (key) {
    const parts = key.split('|');
    const closer = parts[0], date = parts[1], kind = parts[2];
    const rule = TREAT_RULES[kind];
    groups[key].forEach(function (r, idx) {
      const overCap = (kind !== '部位') && (idx >= rule.dailyMax);
      if (overCap) {
        if (targets.indexOf(closer) !== -1) {
          ensure(closer).detail.push({ date: date, label: kind + '（1日上限超）', amount: 0 });
        }
        return;
      }
      const base = (kind === '部位') ? rule.amount * (Number(r['数量']) || 1) : rule.amount;
      const head = saleById[String(r['会計ID'])] || {};
      const appointer = head['アポインター'] || '';
      if (appointer && appointer !== closer) {
        const half = Math.round(base / 2);
        if (targets.indexOf(closer) !== -1) {
          ensure(closer).treat += half;
          ensure(closer).detail.push({ date: date, label: kind + '（折半）', amount: half });
        }
        if (targets.indexOf(appointer) !== -1) {
          ensure(appointer).treat += base - half;
          ensure(appointer).detail.push({ date: date, label: kind + '（アポ折半）', amount: base - half });
        }
      } else if (targets.indexOf(closer) !== -1) {
        ensure(closer).treat += base;
        ensure(closer).detail.push({ date: date, label: kind, amount: base });
      }
    });
  });

  // ② 契約インセンティブ（月内の件数で 5% → 8% → 10%。ラジショット・部位チケットは5%固定で件数に数えない）
  const counters = {};
  items.filter(function (r) { return r['種別'] === '契約'; })
    .sort(function (a, b) { return ymd_(a['日付']) < ymd_(b['日付']) ? -1 : 1; })
    .forEach(function (r) {
      const staff = r['担当者'] || '';
      if (targets.indexOf(staff) === -1) return;
      const netAmt = Number(r['税抜金額']) || 0;
      const noCount = NO_COUNT_CONTRACTS.indexOf(r['区分']) !== -1;
      let rate, label;
      if (noCount) {
        rate = RATE_FIXED5; label = r['名称'] + '（' + r['区分'] + '・5%）';
      } else {
        counters[staff] = (counters[staff] || 0) + 1;
        rate = contractRate_(counters[staff]);
        label = r['名称'] + '（' + counters[staff] + '件目・' + Math.round(rate * 100) + '%）';
      }
      const amt = Math.floor(netAmt * rate);
      ensure(staff).contract += amt;
      ensure(staff).detail.push({ date: ymd_(r['日付']), label: label, amount: amt });
    });

  // ③ 物販10% ④ 定期便5%（初回は対象外）⑤ 調整
  items.forEach(function (r) {
    const staff = r['担当者'] || '';
    if (targets.indexOf(staff) === -1) return;
    const netAmt = Number(r['税抜金額']) || 0;
    const first = (r['初回'] === true || r['初回'] === 'TRUE');
    if (r['種別'] === '物販') {
      const amt = Math.floor(netAmt * RATE_PRODUCT);
      ensure(staff).product += amt;
      ensure(staff).detail.push({ date: ymd_(r['日付']), label: r['名称'] + '（物販10%）', amount: amt });
    } else if (r['種別'] === '定期便') {
      if (first) {
        ensure(staff).detail.push({ date: ymd_(r['日付']), label: r['名称'] + '（定期便・初回は対象外）', amount: 0 });
      } else {
        const amt = Math.floor(netAmt * RATE_SUBSCRIBE);
        ensure(staff).subscribe += amt;
        ensure(staff).detail.push({ date: ymd_(r['日付']), label: r['名称'] + '（定期便5%）', amount: amt });
      }
    } else if (r['種別'] === '調整') {
      ensure(staff).adjust += netAmt;
      ensure(staff).detail.push({ date: ymd_(r['日付']), label: r['名称'] + '（調整）', amount: netAmt });
    }
  });

  Object.keys(result).forEach(function (k) {
    const r = result[k];
    r.total = r.treat + r.contract + r.product + r.subscribe + r.adjust;
    r.detail.sort(function (a, b) { return a.date < b.date ? -1 : 1; });
  });
  return { month: month, staff: Object.keys(result).map(function (k) { return result[k]; }) };
}

// ─── 税理士向けCSV ─────────────────────────────────
function csvCell_(v) {
  const s = (v == null ? '' : String(v));
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
function exportCsv(month) {
  if (!month) month = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM');
  const all = loadAll_();
  const saleById = {};
  all.sales.forEach(function (s) { saleById[String(s['会計ID'])] = s; });
  const payBySale = {};
  all.payments.forEach(function (p) {
    const k = String(p['会計ID']);
    if (!payBySale[k]) payBySale[k] = [];
    payBySale[k].push((p['支払方法'] || '') + (p['状態'] === '未収' ? '(未収)' : '') + ':' + (Number(p['金額']) || 0));
  });

  const rows = [['日付', '顧客名', '担当者', '種別', '名称', '数量', '税率', '税抜金額', '税込金額', '支払方法', '備考']];
  all.items.filter(function (r) { return ymd_(r['日付']).slice(0, 7) === month; })
    .sort(function (a, b) { return ymd_(a['日付']) < ymd_(b['日付']) ? -1 : 1; })
    .forEach(function (r) {
      const h = saleById[String(r['会計ID'])] || {};
      rows.push([ymd_(r['日付']), h['顧客名'] || '', r['担当者'] || '', r['種別'], r['名称'],
                 Number(r['数量']) || 1, Number(r['税率']) || 0,
                 Number(r['税抜金額']) || 0, Number(r['税込金額']) || 0,
                 (payBySale[String(r['会計ID'])] || []).join(' / '), r['備考'] || '']);
    });

  const stockRows = [[''], ['■ 在庫払出（売上ではない持ち出し）'], ['日付', '商品名', '数量', '用途', '金額', 'メモ']];
  getStocks({ month: month }).forEach(function (s) {
    stockRows.push([s.date, s.name, s.qty, s.use, s.amount, s.memo || '']);
  });

  const body = rows.concat(stockRows).map(function (r) {
    return r.map(csvCell_).join(',');
  }).join('\r\n');
  return { month: month, filename: 'ベモーレ売上_' + month + '.csv', csv: body };
}

function setupTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  return { ok: true };
}
