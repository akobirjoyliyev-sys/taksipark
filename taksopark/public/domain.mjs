// NAVO TAXI — © 2026 Jovliyev Akobir Olimjon o‘g‘li. Barcha huquqlar himoyalangan. Ruxsatsiz nusxalash, tarqatish va sotish taqiqlanadi.
export const places = [
  {id:'amir',name:'Amir Temur xiyoboni',area:'Yunusobod tumani',x:60,y:44,lat:41.3111,lon:69.2797},
  {id:'city',name:'Tashkent City',area:'Shayxontohur tumani',x:29,y:48,lat:41.3167,lon:69.2480},
  {id:'airport',name:'Toshkent aeroporti',area:'Sergeli tumani',x:60,y:87,lat:41.2579,lon:69.2812},
  {id:'chorsu',name:'Chorsu bozori',area:'Shayxontohur tumani',x:20,y:27,lat:41.3268,lon:69.2369},
  {id:'tashkent',name:'Toshkent vokzali',area:'Mirobod tumani',x:75,y:67,lat:41.2905,lon:69.2866},
  {id:'minor',name:'Minor masjidi',area:'Yunusobod tumani',x:52,y:16,lat:41.3356,lon:69.2757},
  {id:'magic',name:'Magic City',area:'Chilonzor tumani',x:25,y:72,lat:41.3026,lon:69.2468},
  {id:'ecopark',name:'Ekopark',area:'Mirzo Ulug‘bek tumani',x:83,y:30,lat:41.3098,lon:69.2964}
];
export const labels={pending:'Yangi',accepted:'Haydovchi yo‘lda',arrived:'Haydovchi yetib keldi',riding:'Safarda',completed:'Yakunlangan',cancelled:'Bekor qilingan'};
export const active=s=>!['completed','cancelled'].includes(s);
export const money=n=>new Intl.NumberFormat('en-US').format(Math.round(n||0)).replace(/,/g,' ');
export function quote(state,from,to,tariff){
  const a=places.find(p=>p.id===from),b=places.find(p=>p.id===to),t=state.tariffs.find(t=>t.id===tariff);
  if(!a||!b||a.id===b.id||!t) throw Error('Jo‘nash, manzil va tarifni to‘g‘ri tanlang.');
  const rad=n=>n*Math.PI/180;
  const h=Math.sin(rad(b.lat-a.lat)/2)**2+Math.cos(rad(a.lat))*Math.cos(rad(b.lat))*Math.sin(rad(b.lon-a.lon)/2)**2;
  const km=Math.round(6371*2*Math.atan2(Math.sqrt(h),Math.sqrt(1-h))*1.35*10)/10;
  return {km,minutes:Math.max(4,Math.round(km*3)),price:Math.ceil((t.base+km*t.perKm)/500)*500};
}
export function seed(){
  const now=Date.now();
  const drivers=[
    {id:'d1',name:'Aziz Karimov',phone:'+998901110101',car:'Chevrolet Cobalt',plate:'01 A 707 AA',online:true,blocked:false,rating:4.9},
    {id:'d2',name:'Sardor Aliyev',phone:'+998901110102',car:'Chevrolet Onix',plate:'01 B 212 AB',online:true,blocked:false,rating:4.8},
    {id:'d3',name:'Dilshod Umarov',phone:'+998901110103',car:'Chevrolet Gentra',plate:'01 C 909 AC',online:false,blocked:false,rating:4.9},
    {id:'d4',name:'Javohir Akbarov',phone:'+998901110104',car:'BYD Chazor',plate:'01 D 505 AD',online:true,blocked:false,rating:5.0}
  ];
  return {settings:{name:'NAVO TAXI',city:'Toshkent',phone:'+998 71 000 00 00',commission:12},tariffs:[{id:'economy',name:'Ekonom',base:5000,perKm:1800,desc:'Har kun uchun qulay'},{id:'comfort',name:'Komfort',base:7000,perKm:2400,desc:'Kengroq, qulayroq'},{id:'business',name:'Biznes',base:12000,perKm:3500,desc:'Yuqori darajadagi safar'}],drivers,orders:[
    {id:'NV-1048',riderId:'demo-rider-other',rider:'Madina R.',phone:'+998900000001',from:'city',to:'airport',tariff:'comfort',price:29500,km:9.2,minutes:28,status:'pending',driverId:null,createdAt:now-90000,commission:12},
    {id:'NV-1047',riderId:'demo-rider-other',rider:'Jasur A.',phone:'+998900000002',from:'chorsu',to:'amir',tariff:'economy',price:17000,km:6.4,minutes:19,status:'riding',driverId:'d2',createdAt:now-1200000,commission:12},
    ...Array.from({length:18},(_,i)=>({id:`NV-${1046-i}`,riderId:'history',rider:['Malika S.','Akmal T.','Shahzod B.'][i%3],phone:'+998900000000',from:places[i%8].id,to:places[(i+3)%8].id,tariff:['economy','comfort','business'][i%3],price:15000+(i%7)*3500,km:4.5+i%6,minutes:15+i,status:'completed',driverId:drivers[i%4].id,createdAt:now-i*3600000-2400000,completedAt:now-i*3600000-600000,commission:12}))
  ],audit:[],nextOrder:1049};
}
export function freshState(){const s=seed();return {...s,drivers:[],orders:[],audit:[],nextOrder:1001};}
function text(v,label,max=80){if(typeof v!=='string'||!v.trim()||v.trim().length>max)throw Error(`${label}: to‘g‘ri qiymat kiriting.`);return v.trim();}
export function normalizePhone(v){const p=String(v||'').replace(/[\s()-]/g,'');if(!/^\+998\d{9}$/.test(p))throw Error('Telefon +998 bilan va 9 ta raqamdan iborat bo‘lsin.');return p;}
export function applyAction(state,user,action,p){
  const s=structuredClone(state),admin=user.role==='admin';
  const check=(ok,msg='Bu amal uchun ruxsat yo‘q.')=>{if(!ok)throw Error(msg);};
  if(action==='order.create'){
    check(admin||user.role==='rider');
    const riderId=admin?`dispatch-${Date.now()}`:user.id;
    check(!s.orders.some(o=>o.riderId===riderId&&active(o.status)),'Sizda hali yakunlanmagan buyurtma bor.');
    const q=quote(s,p.from,p.to,p.tariff);
    s.orders.unshift({id:`NV-${s.nextOrder++}`,riderId,rider:admin?text(p.rider,'Ism'):user.name,phone:admin?normalizePhone(p.phone):user.phone,from:p.from,to:p.to,tariff:p.tariff,...q,status:'pending',driverId:null,createdAt:Date.now(),commission:s.settings.commission});
  } else if(action==='order.assign'){
    check(admin||user.role==='driver');const o=s.orders.find(o=>o.id===p.id),d=s.drivers.find(d=>d.id===(admin?p.driverId:user.driverId));
    check(o?.status==='pending','Buyurtma boshqa haydovchiga berilgan yoki faol emas.');
    check(d&&!d.blocked&&d.online,'Haydovchi mavjud emas yoki oflayn.');
    check(!s.orders.some(o=>o.driverId===d.id&&active(o.status)),'Haydovchi hozir band.');
    o.driverId=d.id;o.status='accepted';
  } else if(action==='order.status'){
    const o=s.orders.find(o=>o.id===p.id);check(!!o,'Buyurtma topilmadi.');
    if(p.status==='cancelled')check((admin&&active(o.status))||(user.role==='rider'&&o.riderId===user.id&&['pending','accepted'].includes(o.status)),'Bu bosqichda bekor qilish mumkin emas.');
    else {check(admin||(user.role==='driver'&&o.driverId===user.driverId&&!s.drivers.find(d=>d.id===user.driverId)?.blocked));check(({accepted:'arrived',arrived:'riding',riding:'completed'})[o.status]===p.status,'Buyurtma bosqichi noto‘g‘ri.');}
    o.status=p.status;if(p.status==='completed')o.completedAt=Date.now();
  } else if(action==='driver.online'){
    const d=s.drivers.find(d=>d.id===(admin?p.id:user.driverId));check(!!d&&(admin||user.role==='driver'));check(!d.blocked,'Profil bloklangan. Admin bilan bog‘laning.');
    check(typeof p.online==='boolean');check(p.online||!s.orders.some(o=>o.driverId===d.id&&active(o.status)),'Avval faol safarni yakunlang.');d.online=p.online;
  } else if(action==='driver.save'){
    check(admin);const d={id:p.id||`d-${Date.now()}`,name:text(p.name,'Ism'),phone:normalizePhone(p.phone),car:text(p.car,'Avtomobil'),plate:text(p.plate,'Davlat raqami',20)};
    check(!s.drivers.some(x=>x.id!==d.id&&(x.phone===d.phone||x.plate===d.plate)),'Bu telefon yoki davlat raqami allaqachon mavjud.');
    const i=s.drivers.findIndex(x=>x.id===d.id);if(i>=0)s.drivers[i]={...s.drivers[i],...d};else s.drivers.push({...d,online:false,blocked:false,rating:0});
  } else if(action==='driver.block'){
    check(admin);const d=s.drivers.find(x=>x.id===p.id);check(!!d);check(!s.orders.some(o=>o.driverId===d.id&&active(o.status)),'Avval haydovchining faol safarini yakunlang yoki bekor qiling.');d.blocked=!d.blocked;if(d.blocked)d.online=false;
  } else if(action==='settings.save'){
    check(admin);const c=Number(p.commission);check(Number.isFinite(c)&&c>=0&&c<=40,'Komissiya 0–40% oralig‘ida bo‘lsin.');
    s.settings={name:text(p.name,'Park nomi',32),city:text(p.city,'Shahar',40),phone:normalizePhone(p.phone),commission:c};
  } else if(action==='tariff.save'){
    check(admin);const t=s.tariffs.find(t=>t.id===p.id);check(!!t);const base=Number(p.base),perKm=Number(p.perKm);check(Number.isFinite(base)&&Number.isFinite(perKm)&&base>=0&&base<=1000000&&perKm>0&&perKm<=100000,'Tarif qiymatlarini tekshiring.');t.base=base;t.perKm=perKm;
  } else throw Error('Noma’lum amal.');
  s.audit.unshift({at:Date.now(),user:user.name,action,detail:p.id||''});s.audit=s.audit.slice(0,500);
  return s;
}
export function visibleState(s,u){
  if(u.role==='admin')return s;
  return {...s,audit:[],orders:s.orders.filter(o=>u.role==='rider'?o.riderId===u.id:(o.driverId===u.driverId||o.status==='pending')).map(o=>u.role==='driver'&&o.driverId!==u.driverId?{...o,phone:'',rider:'Yo‘lovchi'}:o),drivers:s.drivers.filter(d=>u.role==='driver'?d.id===u.driverId:s.orders.some(o=>o.riderId===u.id&&o.driverId===d.id)).map(d=>({...d,phone:d.phone}))};
}
