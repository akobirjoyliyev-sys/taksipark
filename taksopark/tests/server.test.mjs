import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {once} from 'node:events';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
test('API auth, trip flow, permissions, atomic assignment and persistence',async()=>{
 const data=mkdtempSync(path.join(tmpdir(),'navo-test-')),port=45329,base=`http://127.0.0.1:${port}`;
 let running;
 const envKeys=['PORT','DATA_DIR','ADMIN_PASSWORD','ADMIN_PHONE'];
 const oldEnv=Object.fromEntries(envKeys.map(k=>[k,process.env[k]]));
 async function start(){Object.assign(process.env,{PORT:String(port),DATA_DIR:data,ADMIN_PASSWORD:'Test-Admin-48251!',ADMIN_PHONE:'+998900000000'});running=await import(pathToFileURL(path.join(root,'server.mjs')).href+'?test='+Date.now());if(!running.server.listening)await once(running.server,'listening');}
 async function stop(){if(running){await running.shutdown();running=null;}}
 async function req(route,body,token){const res=await fetch(base+'/api/'+route,{method:body?'POST':'GET',headers:{Connection:'close',...(body?{'Content-Type':'application/json'}:{}),...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});return {status:res.status,...await res.json()};}
 try{
  await start();assert.equal((await req('state')).status,401);
  const admin=await req('login',{phone:'+998900000000',password:'Test-Admin-48251!'});assert.equal(admin.status,200);assert.equal(admin.state.orders.length,0);
  const rider=await req('register',{phone:'+998909000001',password:'Test-Rider-48251!',name:'Test Rider',role:'admin'});assert.equal(rider.user.role,'rider');
  assert.equal((await req('action',{action:'settings.save',payload:{name:'HACK'}},rider.token)).status,400);
  const createDriver=await req('action',{action:'driver.save',payload:{name:'Test Driver',phone:'+998909000002',car:'Cobalt',plate:'01 A 100 AA',password:'Test-Driver-48251!'}},admin.token);assert.equal(createDriver.status,200);
  const driver=await req('login',{phone:'+998909000002',password:'Test-Driver-48251!'});assert.equal(driver.user.role,'driver');
  await req('action',{action:'driver.online',payload:{online:true}},driver.token);
  const created=await req('action',{action:'order.create',payload:{from:'amir',to:'airport',tariff:'comfort',price:1}},rider.token);assert.equal(created.status,200);const order=created.state.orders[0];assert.ok(order.price>1000);
  const pending=await req('state',undefined,driver.token);assert.equal(pending.state.orders[0].phone,'');
  const competing=await Promise.all([1,2].map(()=>req('action',{action:'order.assign',payload:{id:order.id}},driver.token)));assert.deepEqual(competing.map(r=>r.status).sort(),[200,400]);
  assert.equal((await req('action',{action:'order.status',payload:{id:order.id,status:'completed'}},rider.token)).status,400);
  for(const status of ['arrived','riding','completed'])assert.equal((await req('action',{action:'order.status',payload:{id:order.id,status}},driver.token)).status,200);
  const update=await req('action',{action:'settings.save',payload:{name:'TEST PARK',city:'Toshkent',phone:'+998901234567',commission:15}},admin.token);assert.equal(update.status,200);
  const r2=await req('register',{phone:'+998909000003',password:'Test-Rider-48251!',name:'Other Rider'});assert.equal(r2.state.orders.length,0);
  const bad=await req('action',{action:'driver.save',payload:{name:'Wrong',phone:r2.user.phone,car:'Car',plate:'01 A 999 ZZ',password:'Test-Driver-48251!'}},admin.token);assert.equal(bad.status,400);assert.equal((await req('state',undefined,admin.token)).state.drivers.length,1);
  await stop();await start();const persisted=await req('state',undefined,rider.token);assert.equal(persisted.state.settings.name,'TEST PARK');assert.equal(persisted.state.orders[0].status,'completed');
  const changed=await req('password',{oldPassword:'Test-Rider-48251!',password:'Test-New-48251!'},rider.token);assert.equal(changed.status,200);
  assert.equal((await req('login',{phone:rider.user.phone,password:'Test-Rider-48251!'})).status,401);
  assert.equal((await req('login',{phone:rider.user.phone,password:'Test-New-48251!'})).status,200);
  await req('logout',{},admin.token);assert.equal((await req('state',undefined,admin.token)).status,401);
 } finally {await stop();for(const k of envKeys){if(oldEnv[k]===undefined)delete process.env[k];else process.env[k]=oldEnv[k];}const resolved=path.resolve(data);assert.ok(resolved.startsWith(path.resolve(tmpdir())+path.sep)&&path.basename(resolved).startsWith('navo-test-'));rmSync(resolved,{recursive:true,force:true});}
});

