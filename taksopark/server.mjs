// NAVO TAXI — © 2026 Jovliyev Akobir Olimjon o‘g‘li. Barcha huquqlar himoyalangan. Ruxsatsiz nusxalash, tarqatish va sotish taqiqlanadi.
import http from 'node:http';
import {DatabaseSync} from 'node:sqlite';
import {scryptSync,randomBytes,timingSafeEqual,createHash} from 'node:crypto';
import {readFileSync,existsSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {applyAction,freshState,normalizePhone,visibleState} from './public/domain.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
const dir=process.env.DATA_DIR||path.join(root,'data');mkdirSync(dir,{recursive:true});
const imageDir=path.join(dir,'images');mkdirSync(imageDir,{recursive:true});
const db=new DatabaseSync(path.join(dir,'park.sqlite'));
db.exec(`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,phone TEXT NOT NULL UNIQUE,role TEXT NOT NULL,driverId TEXT,password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,userId TEXT NOT NULL REFERENCES users(id),expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY,json TEXT NOT NULL);`);
function hash(password){const salt=randomBytes(16).toString('hex');return salt+':'+scryptSync(password,salt,64).toString('hex');}
function verify(password,stored){const [salt,h]=stored.split(':');return timingSafeEqual(Buffer.from(h,'hex'),scryptSync(password,salt,64));}
function validPassword(p){if(typeof p!=='string'||p.length<10||p.length>128)throw Error('Parol kamida 10, ko‘pi bilan 128 ta belgidan iborat bo‘lsin.');}
if(!db.prepare('SELECT id FROM state WHERE id=1').get())db.prepare('INSERT INTO state VALUES(1,?)').run(JSON.stringify(freshState()));
if(!db.prepare("SELECT id FROM users WHERE role='admin'").get()){
  const password=process.env.ADMIN_PASSWORD||randomBytes(12).toString('base64url');validPassword(password);
  const phone=normalizePhone(process.env.ADMIN_PHONE||'+998900000000');
  db.prepare('INSERT INTO users VALUES(?,?,?,?,?,?)').run('admin','Administrator',phone,'admin',null,hash(password));
  writeFileSync(path.join(dir,'first-login.txt'),`Admin telefon: ${phone}\nParol: ${password}\nBirinchi kirishdan keyin profil orqali parolni almashtiring va bu faylni o‘chiring.\n`,{mode:0o600});
  console.log('Admin kirish ma’lumotlari: '+path.join(dir,'first-login.txt'));
}
const readState=()=>JSON.parse(db.prepare('SELECT json FROM state WHERE id=1').get().json);
const saveState=s=>db.prepare('UPDATE state SET json=? WHERE id=1').run(JSON.stringify(s));
const publicUser=u=>({id:u.id,name:u.name,phone:u.phone,role:u.role,driverId:u.driverId});
const tokenHash=t=>createHash('sha256').update(t).digest('hex');
const attempts=new Map();
function rate(req){const key=req.socket.remoteAddress;const n=Date.now();const v=attempts.get(key)||{n:0,t:n};if(n-v.t>900000){v.n=0;v.t=n;}v.n++;attempts.set(key,v);if(v.n>40)throw Error('Urinishlar juda ko‘p. 15 daqiqadan keyin qayta urinib ko‘ring.');}
const cleanupTimer=setInterval(()=>{const now=Date.now();for(const [key,v]of attempts)if(now-v.t>900000)attempts.delete(key);db.prepare('DELETE FROM sessions WHERE expires<?').run(now);},60000);cleanupTimer.unref();
async function body(req,max=32000){let str='';for await(const chunk of req){str+=chunk;if(str.length>max)throw Error('So‘rov juda katta.');}try{return JSON.parse(str||'{}');}catch{throw Error('JSON noto‘g‘ri.');}}
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  const allowed=['https://appassets.androidplatform.net',...(process.env.ALLOWED_ORIGINS||'').split(',').filter(Boolean)];
  const origin=req.headers.origin;
  if(origin&&allowed.includes(origin))res.setHeader('Access-Control-Allow-Origin',origin);
  res.setHeader('Vary','Origin');res.setHeader('Access-Control-Allow-Headers','Content-Type, Authorization');res.setHeader('Access-Control-Allow-Methods','GET,POST,OPTIONS');
  res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer');res.setHeader('X-Frame-Options','DENY');
  const json=(status,obj)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(obj));};
  if(req.method==='OPTIONS'){res.writeHead(204);res.end();return;}
  try{
    if(req.method==='GET'&&url.pathname.startsWith('/images/')){
      const m=/^\/images\/([a-f0-9]{24}\.(jpg|png|webp))$/.exec(url.pathname),f=m&&path.join(imageDir,m[1]);
      if(!f||!existsSync(f))return json(404,{error:'Rasm topilmadi.'});
      res.writeHead(200,{'Content-Type':{jpg:'image/jpeg',png:'image/png',webp:'image/webp'}[m[2]],'Cache-Control':'public, max-age=31536000, immutable'});res.end(readFileSync(f));return;
    }
    if(!url.pathname.startsWith('/api/')){
      if(req.method!=='GET')return json(405,{error:'Usul ruxsat etilmagan.'});
      const rel=url.pathname==='/'?'index.html':decodeURIComponent(url.pathname.slice(1));
      const f=path.resolve(root,'public',rel),base=path.resolve(root,'public')+path.sep;
      if(!f.startsWith(base)||!existsSync(f))return json(404,{error:'Sahifa topilmadi.'});
      res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tile.openstreetmap.org; font-src 'self'; connect-src 'self' https:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'");
      res.setHeader('Content-Type',({'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.js':'text/javascript; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2','.txt':'text/plain; charset=utf-8'})[path.extname(f)]||'application/octet-stream');
      res.end(readFileSync(f));return;
    }
    if(url.pathname==='/api/health')return json(200,{ok:true,name:readState().settings.name});
    if(req.method==='POST'&&['/api/login','/api/register'].includes(url.pathname)){
      rate(req);const p=await body(req);const phone=normalizePhone(p.phone);validPassword(p.password);
      if(url.pathname==='/api/register'){
        if(typeof p.name!=='string'||!p.name.trim()||p.name.length>80)throw Error('Ismingizni kiriting.');
        if(db.prepare('SELECT id FROM users WHERE phone=?').get(phone))throw Error('Bu telefon ro‘yxatdan o‘tgan.');
        db.prepare('INSERT INTO users VALUES(?,?,?,?,?,?)').run(randomBytes(12).toString('hex'),p.name.trim(),phone,'rider',null,hash(p.password));
      }
      const u=db.prepare('SELECT * FROM users WHERE phone=?').get(phone);
      if(!u||!verify(p.password,u.password))return json(401,{error:'Telefon yoki parol xato.'});
      if(u.role==='driver'&&readState().drivers.find(d=>d.id===u.driverId)?.blocked)return json(403,{error:'Profil bloklangan.'});
      const token=randomBytes(32).toString('hex');db.prepare('INSERT INTO sessions VALUES(?,?,?)').run(tokenHash(token),u.id,Date.now()+12*3600000);
      return json(200,{token,user:publicUser(u),state:visibleState(readState(),u)});
    }
    const raw=req.headers.authorization?.replace(/^Bearer /,'')||'';
    const session=db.prepare('SELECT * FROM sessions WHERE token=? AND expires>?').get(tokenHash(raw),Date.now());
    if(!session)return json(401,{error:'Hisobingizga qayta kiring.'});
    const u=db.prepare('SELECT * FROM users WHERE id=?').get(session.userId);
    if(u.role==='driver'&&readState().drivers.find(d=>d.id===u.driverId)?.blocked)return json(403,{error:'Profil bloklangan.'});
    if(req.method==='GET'&&url.pathname==='/api/state')return json(200,{state:visibleState(readState(),u),user:publicUser(u)});
    if(req.method==='POST'&&url.pathname==='/api/logout'){db.prepare('DELETE FROM sessions WHERE token=?').run(tokenHash(raw));return json(200,{ok:true});}
    if(req.method==='POST'&&url.pathname==='/api/password'){
      const p=await body(req);validPassword(p.password);if(!verify(p.oldPassword||'',u.password))throw Error('Eski parol noto‘g‘ri.');
      db.prepare('UPDATE users SET password=? WHERE id=?').run(hash(p.password),u.id);db.prepare('DELETE FROM sessions WHERE userId=? AND token<>?').run(u.id,tokenHash(raw));return json(200,{ok:true});
    }
    if(req.method==='POST'&&url.pathname==='/api/image'){
      if(u.role!=='admin')return json(403,{error:'Rasmni faqat administrator yuklaydi.'});
      const m=/^data:image\/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)$/.exec((await body(req,2000000)).data||'');if(!m)throw Error('Rasm JPG, PNG yoki WEBP bo‘lsin.');
      const buf=Buffer.from(m[2],'base64'),magic={jpeg:[0xff,0xd8,0xff],png:[0x89,0x50,0x4e,0x47],webp:[0x52,0x49,0x46,0x46]}[m[1]];
      if(buf.length>1400000)throw Error('Rasm juda katta.');if(!magic.every((b,i)=>buf[i]===b))throw Error('Rasm fayli buzilgan.');
      const name=randomBytes(12).toString('hex')+'.'+(m[1]==='jpeg'?'jpg':m[1]);writeFileSync(path.join(imageDir,name),buf);return json(200,{url:'/images/'+name});
    }
    if(req.method==='POST'&&url.pathname==='/api/action'){
      const {action,payload:p}=await body(req);if(!p||typeof p!=='object')throw Error('Ma’lumot noto‘g‘ri.');
      db.exec('BEGIN IMMEDIATE');
      try{
        const s=applyAction(readState(),u,action,p);
        if(action==='driver.save'){
          const d=s.drivers.find(d=>d.phone===normalizePhone(p.phone));
          const existing=db.prepare('SELECT id FROM users WHERE driverId=?').get(d.id);
          const used=db.prepare('SELECT id FROM users WHERE phone=?').get(d.phone);
          if(used&&used.id!==existing?.id)throw Error('Bu telefon boshqa hisobga tegishli.');
          if(!existing){validPassword(p.password);db.prepare('INSERT INTO users VALUES(?,?,?,?,?,?)').run(randomBytes(12).toString('hex'),d.name,d.phone,'driver',d.id,hash(p.password));}
          else {db.prepare('UPDATE users SET name=?,phone=? WHERE id=?').run(d.name,d.phone,existing.id);if(p.password){validPassword(p.password);db.prepare('UPDATE users SET password=? WHERE id=?').run(hash(p.password),existing.id);db.prepare('DELETE FROM sessions WHERE userId=?').run(existing.id);}}
        }
        saveState(s);db.exec('COMMIT');return json(200,{state:visibleState(s,u)});
      }catch(e){db.exec('ROLLBACK');throw e;}
    }
    return json(404,{error:'API topilmadi.'});
  }catch(e){json(400,{error:e.message?.includes('UNIQUE')?'Bu ma’lumot allaqachon mavjud.':e.message||'So‘rov bajarilmadi.'});}
});
const port=Number(process.env.PORT)||4317;
server.listen(port,process.env.HOST||'127.0.0.1',()=>console.log(`Taksopark: http://localhost:${port}`));
export {server};
export async function shutdown(){clearInterval(cleanupTimer);await new Promise((resolve,reject)=>{server.close(e=>e?reject(e):resolve());server.closeIdleConnections();});db.close();}
