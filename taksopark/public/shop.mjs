// NAVO TAXI — © 2026 Jovliyev Akobir Olimjon o‘g‘li. Barcha huquqlar himoyalangan. Ruxsatsiz nusxalash, tarqatish va sotish taqiqlanadi.
// Do‘kon: katalog, savat, buyurtma va kuryer orqali yetkazib berish.
export const shopLabels={new:'Yangi',packing:'Yig‘ilmoqda',ready:'Kuryer kutilmoqda',delivering:'Yo‘lda',delivered:'Yetkazildi',cancelled:'Bekor qilingan'};
export const shopActive=s=>!['delivered','cancelled'].includes(s);
export const shopNext={new:'packing',packing:'ready',delivering:'delivered'};
const defaultCategories=[{id:'food',name:'Oziq-ovqat',emoji:'🍞'},{id:'fruit',name:'Meva va sabzavot',emoji:'🍎'},{id:'drinks',name:'Ichimliklar',emoji:'🥤'},{id:'sweets',name:'Shirinliklar',emoji:'🍰'},{id:'home',name:'Uy-ro‘zg‘or',emoji:'🧴'}];
export function freshShop(){return {settings:{open:true,deliveryFee:10000,freeFrom:200000,minOrder:30000},categories:structuredClone(defaultCategories),products:[],orders:[],nextOrder:1001};}
export function shopSeed(now=Date.now()){
  const P=(id,categoryId,name,price,unit,stock,emoji,desc='')=>({id,categoryId,name,price,unit,stock,emoji,desc,image:'',active:true});
  const products=[
    P('p1','food','Tandir non',4000,'1 dona',120,'🫓','Har kuni ertalab yangi yopiladi.'),
    P('p2','food','Guruch «Devzira»',24000,'1 kg',60,'🍚','Osh uchun saralangan guruch.'),
    P('p3','food','Paxta yog‘i',26000,'1 litr',40,'🫗'),
    P('p4','food','Tuxum',17000,'10 dona',50,'🥚'),
    P('p5','food','Sut',12000,'1 litr',30,'🥛','Mahalliy fermadan.'),
    P('p6','fruit','Surxon anori',15000,'1 kg',80,'🍎','Shirin, yirik donali anor.'),
    P('p7','fruit','Xurmo',12000,'1 kg',70,'🟠'),
    P('p8','fruit','Limon',18000,'1 kg',4,'🍋'),
    P('p9','fruit','Pomidor',10000,'1 kg',90,'🍅'),
    P('p10','drinks','Mineral suv',4000,'1,5 litr',200,'💧'),
    P('p11','drinks','Ko‘k choy',18000,'100 g',35,'🍵'),
    P('p12','sweets','Napoleon torti',85000,'1 kg',6,'🍰','Buyurtma kuni tayyorlanadi.'),
    P('p13','sweets','Qand',14000,'1 kg',45,'🧊'),
    P('p14','home','Kir yuvish kukuni',65000,'3 kg',20,'🧴'),
    P('p15','home','Idish yuvish vositasi',16000,'1 litr',0,'🧽')
  ];
  const line=(id,qty)=>{const p=products.find(p=>p.id===id);return {productId:id,name:p.name,unit:p.unit,price:p.price,qty,sum:p.price*qty};};
  const order=(n,customer,items,status,courierId,ago)=>{const subtotal=items.reduce((a,l)=>a+l.sum,0),delivery=subtotal>=200000?0:10000;return {id:`DK-${n}`,customerId:'demo-customer-other',customer,phone:'+998900000005',address:'Qumqo‘rg‘on sh., Navro‘z ko‘chasi, 12-uy',comment:'',items,subtotal,delivery,total:subtotal+delivery,payment:'cash',status,courierId,createdAt:now-ago,...(status==='delivered'?{deliveredAt:now-ago+1800000}:{})};};
  return {settings:{open:true,deliveryFee:10000,freeFrom:200000,minOrder:30000},categories:structuredClone(defaultCategories),products,orders:[
    order(1006,'Nilufar K.',[line('p2',2),line('p3',1),line('p4',1)],'new',null,240000),
    order(1005,'Bobur T.',[line('p12',1),line('p11',1)],'ready',null,1500000),
    order(1004,'Sevara M.',[line('p6',3),line('p9',2),line('p1',4)],'delivered','d2',7200000),
    order(1003,'Otabek R.',[line('p14',1),line('p10',6)],'delivered','d4',30000000),
    order(1002,'Dilnoza A.',[line('p5',2),line('p1',3),line('p13',1)],'delivered','d1',90000000)
  ],nextOrder:1007};
}
export function upgradeShop(s){if(!s.shop)s.shop=freshShop();return s;}
const int=(v,min,max,msg)=>{const n=Number(v);if(!Number.isInteger(n)||n<min||n>max)throw Error(msg);return n;};
export function cartTotals(shop,items){
  if(!Array.isArray(items)||!items.length||items.length>50)throw Error('Savat bo‘sh.');
  const merged=new Map();
  for(const it of items){if(!it||typeof it.id!=='string')throw Error('Savatdagi mahsulot noto‘g‘ri.');merged.set(it.id,(merged.get(it.id)||0)+int(it.qty,1,99,'Mahsulot soni 1 dan 99 gacha bo‘lsin.'));}
  const lines=[...merged].map(([id,qty])=>{const p=shop.products.find(p=>p.id===id);if(!p||!p.active)throw Error('Savatdagi ba’zi mahsulotlar endi sotuvda yo‘q.');if(p.stock<qty)throw Error(`«${p.name}» omborda ${p.stock} ta qoldi.`);return {productId:p.id,name:p.name,unit:p.unit,price:p.price,qty,sum:p.price*qty};});
  const subtotal=lines.reduce((a,l)=>a+l.sum,0),st=shop.settings,delivery=st.freeFrom>0&&subtotal>=st.freeFrom?0:st.deliveryFee;
  return {lines,subtotal,delivery,total:subtotal+delivery};
}
const imageOk=v=>v===''||/^\/images\/[a-f0-9]{24}\.(jpg|png|webp)$/.test(v)||(/^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/.test(v)&&v.length<=400000);
function restock(shop,o){for(const l of o.items){const p=shop.products.find(p=>p.id===l.productId);if(p)p.stock+=l.qty;}}
// h: {check,text,busy,drivers} — domain.mjs dan beriladi.
export function shopAction(s,user,action,p,h){
  const {check,text}=h,shop=s.shop,admin=user.role==='admin';
  const opt=(v,label,max)=>v==null||v===''?'':text(v,label,max);
  if(action==='shop.checkout'){
    check(user.role==='rider','Buyurtmani mijoz hisobidan bering.');check(shop.settings.open,'Do‘kon hozir yopiq. Keyinroq urinib ko‘ring.');
    check(shop.orders.filter(o=>o.customerId===user.id&&shopActive(o.status)).length<3,'Sizda 3 ta yakunlanmagan buyurtma bor.');
    const t=cartTotals(shop,p.items);check(t.subtotal>=shop.settings.minOrder,`Eng kam buyurtma: ${shop.settings.minOrder} so‘m.`);
    for(const l of t.lines)shop.products.find(x=>x.id===l.productId).stock-=l.qty;
    shop.orders.unshift({id:`DK-${shop.nextOrder++}`,customerId:user.id,customer:user.name,phone:user.phone,address:text(p.address,'Manzil',160),comment:opt(p.comment,'Izoh',200),items:t.lines,subtotal:t.subtotal,delivery:t.delivery,total:t.total,payment:'cash',status:'new',courierId:null,createdAt:Date.now()});
  } else if(action==='shop.assign'){
    check(admin||user.role==='driver');const o=shop.orders.find(o=>o.id===p.id),d=s.drivers.find(d=>d.id===(admin?p.driverId:user.driverId));
    check(o?.status==='ready','Buyurtma hali tayyor emas yoki boshqa kuryer olgan.');
    check(d&&!d.blocked&&d.online,'Kuryer mavjud emas yoki oflayn.');check(!h.busy(s,d.id),'Kuryer hozir band.');
    o.courierId=d.id;o.status='delivering';o.pickedAt=Date.now();
  } else if(action==='shop.status'){
    const o=shop.orders.find(o=>o.id===p.id);check(!!o,'Buyurtma topilmadi.');
    if(p.status==='cancelled'){check((admin&&shopActive(o.status))||(user.role==='rider'&&o.customerId===user.id&&o.status==='new'),'Bu bosqichda bekor qilib bo‘lmaydi.');restock(shop,o);}
    else{check(shopNext[o.status]===p.status,'Buyurtma bosqichi noto‘g‘ri.');check(admin||(p.status==='delivered'&&user.role==='driver'&&o.courierId===user.driverId),'Bu amal uchun ruxsat yo‘q.');}
    o.status=p.status;if(p.status==='delivered')o.deliveredAt=Date.now();
  } else if(action==='shop.product.save'){
    check(admin);check(shop.categories.some(c=>c.id===p.categoryId),'Kategoriyani tanlang.');
    const image=p.image==null?undefined:String(p.image);if(image!==undefined)check(imageOk(image),'Rasm noto‘g‘ri yoki juda katta.');
    const d={name:text(p.name,'Mahsulot nomi',80),categoryId:p.categoryId,price:int(p.price,100,100000000,'Narx 100 so‘mdan katta butun son bo‘lsin.'),stock:int(p.stock,0,1000000,'Qoldiq 0 yoki undan katta butun son bo‘lsin.'),unit:text(p.unit,'O‘lchov',20),desc:opt(p.desc,'Tavsif',300),emoji:opt(p.emoji,'Belgi',8),active:p.active===true||p.active==='on'||p.active==='true'};
    const old=shop.products.find(x=>x.id===p.id);
    if(old)Object.assign(old,d,image!==undefined?{image}:{});
    else shop.products.unshift({id:`p-${Date.now().toString(36)}${Math.random().toString(36).slice(2,6)}`,...d,image:image||''});
  } else if(action==='shop.product.delete'){
    check(admin);const i=shop.products.findIndex(x=>x.id===p.id);check(i>=0,'Mahsulot topilmadi.');shop.products.splice(i,1);
  } else if(action==='shop.category.save'){
    check(admin);const name=text(p.name,'Kategoriya nomi',40),emoji=opt(p.emoji,'Belgi',8),c=shop.categories.find(c=>c.id===p.id);
    check(!shop.categories.some(x=>x.id!==p.id&&x.name.toLowerCase()===name.toLowerCase()),'Bu kategoriya allaqachon bor.');
    if(c)Object.assign(c,{name,emoji});else{check(shop.categories.length<40,'Kategoriyalar soni 40 tadan oshmasin.');shop.categories.push({id:`c-${Date.now().toString(36)}`,name,emoji});}
  } else if(action==='shop.category.delete'){
    check(admin);check(!shop.products.some(x=>x.categoryId===p.id),'Avval bu kategoriyadagi mahsulotlarni boshqasiga o‘tkazing yoki o‘chiring.');
    const i=shop.categories.findIndex(c=>c.id===p.id);check(i>=0,'Kategoriya topilmadi.');shop.categories.splice(i,1);
  } else if(action==='shop.settings.save'){
    check(admin);shop.settings={open:p.open===true||p.open==='on'||p.open==='true',deliveryFee:int(p.deliveryFee,0,1000000,'Yetkazish narxini tekshiring.'),freeFrom:int(p.freeFrom,0,1000000000,'Bepul yetkazish chegarasini tekshiring.'),minOrder:int(p.minOrder,0,1000000000,'Eng kam buyurtma summasini tekshiring.')};
  } else throw Error('Noma’lum amal.');
}
export function shopVisible(s,u){
  const shop=s.shop;if(u.role==='admin')return shop;
  if(u.role==='rider')return {...shop,products:shop.products.filter(p=>p.active),orders:shop.orders.filter(o=>o.customerId===u.id)};
  return {...shop,products:[],orders:shop.orders.filter(o=>o.courierId===u.driverId||o.status==='ready').map(o=>o.courierId===u.driverId?o:{...o,phone:'',customer:'Mijoz',comment:''})};
}
