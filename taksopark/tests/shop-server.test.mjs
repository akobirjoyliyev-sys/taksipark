import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {once} from 'node:events';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
test('shop API: image upload, checkout and courier delivery',async()=>{
 const data=mkdtempSync(path.join(tmpdir(),'navo-test-')),port=45330,base=`http://127.0.0.1:${port}`;
 let running;
 const envKeys=['PORT','DATA_DIR','ADMIN_PASSWORD','ADMIN_PHONE'];
 const oldEnv=Object.fromEntries(envKeys.map(k=>[k,process.env[k]]));
 async function req(route,body,token){const res=await fetch(base+'/api/'+route,{method:body?'POST':'GET',headers:{Connection:'close',...(body?{'Content-Type':'application/json'}:{}),...(token?{Authorization:'Bearer '+token}:{})},body:body?JSON.stringify(body):undefined});return {status:res.status,...await res.json()};}
 try{
  Object.assign(process.env,{PORT:String(port),DATA_DIR:data,ADMIN_PASSWORD:'Test-Admin-48251!',ADMIN_PHONE:'+998900000000'});running=await import(pathToFileURL(path.join(root,'server.mjs')).href+'?shop='+Date.now());if(!running.server.listening)await once(running.server,'listening');
  const admin=await req('login',{phone:'+998900000000',password:'Test-Admin-48251!'});assert.equal(admin.state.shop.products.length,0);assert.ok(admin.state.shop.categories.length>0);
  const rider=await req('register',{phone:'+998909000011',password:'Test-Rider-48251!',name:'Mijoz'});
  const png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
  assert.equal((await req('image',{data:png},rider.token)).status,403);
  assert.equal((await req('image',{data:'data:image/png;base64,'+Buffer.from('not an image').toString('base64')},admin.token)).status,400);
  const up=await req('image',{data:png},admin.token);assert.equal(up.status,200);assert.match(up.url,/^\/images\/[a-f0-9]{24}\.png$/);
  const img=await fetch(base+up.url,{headers:{Connection:'close'}});assert.equal(img.status,200);assert.equal(img.headers.get('content-type'),'image/png');await img.arrayBuffer();
  assert.equal((await fetch(base+'/images/../park.sqlite',{headers:{Connection:'close'}})).status,404);
  const saved=await req('action',{action:'shop.product.save',payload:{name:'Anor',categoryId:'fruit',price:15000,stock:10,unit:'1 kg',active:'on',image:up.url}},admin.token);assert.equal(saved.status,200);const p=saved.state.shop.products[0];
  const bought=await req('action',{action:'shop.checkout',payload:{items:[{id:p.id,qty:3}],address:'Qumqo‘rg‘on, 5-uy'}},rider.token);assert.equal(bought.status,200);const o=bought.state.shop.orders[0];assert.equal(o.total,55000);
  const driver=await req('action',{action:'driver.save',payload:{name:'Kuryer',phone:'+998909000012',car:'Damas',plate:'75 A 001 AA',password:'Test-Driver-48251!'}},admin.token);assert.equal(driver.status,200);
  const d=await req('login',{phone:'+998909000012',password:'Test-Driver-48251!'});await req('action',{action:'driver.online',payload:{online:true}},d.token);
  for(const status of ['packing','ready'])assert.equal((await req('action',{action:'shop.status',payload:{id:o.id,status}},admin.token)).status,200);
  const seen=await req('state',undefined,d.token);assert.equal(seen.state.shop.orders[0].phone,'');
  assert.equal((await req('action',{action:'shop.assign',payload:{id:o.id}},d.token)).status,200);
  const done=await req('action',{action:'shop.status',payload:{id:o.id,status:'delivered'}},d.token);assert.equal(done.status,200);
  const mine=await req('state',undefined,rider.token);assert.equal(mine.state.shop.orders[0].status,'delivered');assert.equal(mine.state.shop.products[0].stock,7);
 } finally {if(running)await running.shutdown();for(const k of envKeys){if(oldEnv[k]===undefined)delete process.env[k];else process.env[k]=oldEnv[k];}rmSync(path.resolve(data),{recursive:true,force:true});}
});
