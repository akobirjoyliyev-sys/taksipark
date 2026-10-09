// NAVO TAXI — © 2026 Jovliyev Akobir Olimjon o‘g‘li. Barcha huquqlar himoyalangan. Ruxsatsiz nusxalash, tarqatish va sotish taqiqlanadi.
// Qumqo‘rg‘on tumani manzillari. Koordinatalar taxminiy — ishga tushirishdan oldin joyida tekshiring.
const P=(id,name,area,lat,lon)=>({id,name,area,lat,lon});
export const center={lat:37.8205,lon:67.5852};
export const places=[
  P('markaz','Qumqo‘rg‘on markazi','Markaz',37.8205,67.5852),
  P('hokimlik','Tuman hokimligi','Markaz',37.822,67.584),
  P('bozor','Markaziy dehqon bozori','Markaz',37.8185,67.588),
  P('vokzal','Temir yo‘l vokzali','Markaz',37.812,67.592),
  P('kasalxona','Tuman markaziy kasalxonasi','Markaz',37.8245,67.579),
  P('beshqahramon','Beshqahramon MFY','Mahalla',37.825,67.581),
  P('yangishahar','Yangi shahar MFY','Mahalla',37.822,67.591),
  P('saxovat','Saxovat MFY','Mahalla',37.817,67.575),
  P('surxonsohili','Surxon sohili MFY','Mahalla',37.829,67.596),
  P('bogieram','Bog‘i eram MFY','Mahalla',37.812,67.565),
  P('dostlik','Do‘stlik MFY','Mahalla',37.826,67.571),
  P('hurriyat','Hurriyat','Shaharcha',37.809,67.551),
  P('yangiyer','Yangiyer','Shaharcha',37.815,67.605),
  P('navbahor','Navbahor','Shaharcha',37.815,67.612),
  P('xojamqulov','M. Xo‘jamqulov','Shaharcha',37.842,67.572),
  P('neftchilar','Neftchilar','Shaharcha',37.782,67.592),
  P('qorsoqli','Qorsoqli','Shaharcha',37.8067,67.6442),
  P('elbayon','Elbayon','Shaharcha',37.882,67.521),
  P('bogara','Bog‘ara','Shaharcha',37.854,67.452),
  P('jiydali','Jiydali','Shaharcha',37.892,67.625),
  P('jaloyir','Jaloyir','Shaharcha',37.765,67.542),
  P('azlarsoy','Azlarsoy','Shaharcha',37.925,67.512),
  P('oqsoy','Oqsoy','Shaharcha',37.832,67.692),
  P('ozbekiston','O‘zbekiston QFY','Qishloq',37.831,67.532),
  P('ketmon','Ketmon','Qishloq',37.862,67.594),
  P('tayfang','Tayfang','Qishloq',37.852,67.621),
  P('tuda','Tuda','Qishloq',37.792,67.531),
  P('tugon','Tugon','Qishloq',37.772,67.641),
  P('arslonbosh','Arslonbosh','Qishloq',37.872,67.652),
  P('oqjar','Oqjar','Qishloq',37.748,67.581),
  P('uyas','Uyas','Qishloq',37.755,67.525),
  P('oqqopchigay','Oqqopchig‘ay','Qishloq',37.718,67.632),
  P('kakaydi','Yuqori Kakaydi','Qishloq',37.698,67.682)
];
export const place=id=>places.find(p=>p.id===id);
// Yo‘l masofasi: to‘g‘ri chiziq × 1.3 (tuman yo‘llari uchun taxminiy koeffitsiyent).
export function roadKm(a,b){
  const rad=n=>n*Math.PI/180;
  const h=Math.sin(rad(b.lat-a.lat)/2)**2+Math.cos(rad(a.lat))*Math.cos(rad(b.lat))*Math.sin(rad(b.lon-a.lon)/2)**2;
  return Math.round(6371*2*Math.atan2(Math.sqrt(h),Math.sqrt(1-h))*1.3*10)/10;
}
