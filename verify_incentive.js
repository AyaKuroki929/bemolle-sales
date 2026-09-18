const fs=require('fs'), vm=require('vm');
function run(data){
  const ctx={console,Math,Date,String,Number,Object,Array,Boolean,JSON,isNaN,parseInt,parseFloat,
    Utilities:{formatDate:(d,tz,f)=>{const p=n=>String(n).padStart(2,'0');
      return f.replace('yyyy',d.getFullYear()).replace('MM',p(d.getMonth()+1)).replace('dd',p(d.getDate()));}},
    SpreadsheetApp:{},PropertiesService:{getScriptProperties:()=>({getProperty:()=>null,setProperty:()=>{}})},
    LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})}};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('/Users/ayakuroki/projects/bemolle-sales/Code.gs','utf8'),ctx);
  ctx.readSheet_=n=>JSON.parse(JSON.stringify(data[n]||[]));
  return vm.runInContext("getIncentive('2026-08')",ctx).staff.find(s=>s.staff==='中田有加');
}
const base=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const y=run(JSON.parse(JSON.stringify(base)));
const pay={'08/01':14935,'08/03':5250,'08/05':28194,'08/07':8130,'08/08':18900,'08/10':8570,
 '08/12':2250,'08/17':33212,'08/19':12129,'08/20':38028,'08/21':6770,'08/22':8250,
 '08/24':43800,'08/25':0,'08/26':5250,'08/29':8250,'08/31':6900};
const byday={}; y.detail.forEach(d=>byday[d.date.slice(5).replace('-','/')]=(byday[d.date.slice(5).replace('-','/')]||0)+d.amount);
console.log('【本番データ】有加報酬(紙)と食い違う日だけ表示');
let n=0;
Object.keys(pay).concat(Object.keys(byday)).filter((v,i,a)=>a.indexOf(v)===i).sort().forEach(k=>{
  if((pay[k]||0)!==(byday[k]||0)){console.log(`  ${k} 有加報酬${(pay[k]||0).toLocaleString()} / システム${(byday[k]||0).toLocaleString()} → ${((byday[k]||0)-(pay[k]||0))>0?'+':''}${(byday[k]||0)-(pay[k]||0)}`);n++;}});
if(!n)console.log('  なし');
console.log(`  月合計 有加報酬248,818 / システム${y.total.toLocaleString()}`);
console.log(`  ＋研修1,200 ＋日当80,000 = ${(y.total+1200+80000).toLocaleString()}円`);
// わざと壊す：8/22の上半身6回をなくしてプリペイドだけにする
const broken=JSON.parse(JSON.stringify(base));
broken['明細']=broken['明細'].filter(r=>!(r['日付']==='2026-08-22'&&r['名称']==='上半身6回5%off'));
const b=run(broken);
console.log('\n【わざと壊したとき】8/22の上半身6回を消してプリペイドだけにした');
b.detail.filter(d=>d.date==='2026-08-22').forEach(d=>console.log('  ',d.label,d.amount));
