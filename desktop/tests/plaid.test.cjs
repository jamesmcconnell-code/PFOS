const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {createPlaidVault,testPlaidCredentials}=require('../plaid.cjs');
const values={client_id:'test-client',secret:'test-secret-never-plaintext',environment:'sandbox'};
// A fake OS encryptor isolates disk/logic tests from the developer's real Keychain.
const cipher=Buffer.from('test-os-encrypted-payload');
const secure={isAsyncEncryptionAvailable:async()=>true,encryptStringAsync:async()=>cipher,
  decryptStringAsync:async()=>({result:JSON.stringify(values)})};
test('per-profile vault persists only protected data and never inherits credentials',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'pfos-vault-'));
 try{
  const vault=createPlaidVault(root,secure,'darwin');assert.equal(await vault.load(),null);
  await vault.save(values);
  const disk=await fs.readFile(path.join(root,'plaid-credentials.json'),'utf8');
  assert.ok(!disk.includes(values.secret));assert.deepEqual(await vault.load(),values);
  const second=await fs.mkdtemp(path.join(root,'other-'));
  assert.equal(await createPlaidVault(second,secure,'darwin').load(),null);
  await assert.rejects(createPlaidVault(root,{...secure,isAsyncEncryptionAvailable:async()=>false},'darwin').save(values),/Keychain/);
  assert.equal(await fs.readFile(path.join(root,'plaid-credentials.json'),'utf8'),disk);
 }finally{await fs.rm(root,{recursive:true,force:true})}
});
test('credential validation uses only supplied credentials and a fixed HTTPS Plaid host',async()=>{
 let request;
 const result=await testPlaidCredentials(values,async(url,init)=>{request={url,body:JSON.parse(init.body),redirect:init.redirect};return {ok:true,json:async()=>({link_token:'temporary-token',hosted_link_url:'https://secure.plaid.com/hl/synthetic'})}});
 assert.equal(request.url,'https://sandbox.plaid.com/link/token/create');
 assert.equal(request.body.secret,values.secret);assert.deepEqual(request.body.products,['transactions']);
 assert.equal(request.redirect,'error');assert.ok(!JSON.stringify(result).includes('temporary-token'));
 await assert.rejects(testPlaidCredentials({...values,environment:'evil.invalid'}),/environment/);
});
test('provider errors and network failures never echo secrets',async()=>{
 for(const code of ['INVALID_API_KEYS','INVALID_PRODUCT','UNKNOWN_ERROR']){
  await assert.rejects(testPlaidCredentials(values,async()=>({ok:false,json:async()=>({error_code:code,error_message:values.secret})})),error=>!error.message.includes(values.secret));
 }
 await assert.rejects(testPlaidCredentials(values,async()=>{throw new Error(values.secret)}),/internet connection/);
});
test('Plaid IPC refuses foreign frames and non-admin sessions before reading credentials',async()=>{
 const {registerPlaidIPC}=require('../plaid.cjs');
 let handler,reads=0,authCalls=0;
 const mainFrame={url:'http://127.0.0.1:37841/connections'};
 const webContents={mainFrame};
 const window={isDestroyed:()=>false,webContents};
 const originalFetch=global.fetch;
 global.fetch=async()=>{authCalls++;return {ok:true,json:async()=>({role:'MEMBER'})}};
 try{
  registerPlaidIPC({ipcMain:{handle:(_channel,callback)=>{handler=callback}},vault:{load:async()=>{reads++;return values}},getBackend:()=>({url:'http://127.0.0.1:12345',token:'private-capability'}),getWindow:()=>window,origin:'http://127.0.0.1:37841'});
  const foreign=await handler({sender:webContents,senderFrame:{url:mainFrame.url}},{action:'status',token:'synthetic-jwt'});
  assert.equal(foreign.ok,false);assert.equal(authCalls,0);
  const member=await handler({sender:webContents,senderFrame:mainFrame},{action:'status',token:'synthetic-jwt'});
  assert.equal(member.ok,false);assert.match(member.error,/administrator/);assert.equal(reads,0);
  global.fetch=async()=>({ok:false});
  assert.equal((await handler({sender:webContents,senderFrame:mainFrame},{action:'save',values})).ok,false);
  assert.equal(reads,0);
 }finally{global.fetch=originalFetch}
});
test('vault removal works without Keychain access and is limited to this installation',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'pfos-remove-'));
 try{
  await createPlaidVault(root,secure,'darwin').save(values);
  await fs.writeFile(path.join(root,'keep-financial-data'),'preserved');
  const locked=createPlaidVault(root,{isAsyncEncryptionAvailable:async()=>false},'darwin');
  await locked.remove();await locked.remove();
  assert.equal(await locked.load(),null);
  assert.equal(await fs.readFile(path.join(root,'keep-financial-data'),'utf8'),'preserved');
 }finally{await fs.rm(root,{recursive:true,force:true})}
});
test('replacement requires review and failed validation never changes saved or active keys',async()=>{
 const {registerPlaidIPC}=require('../plaid.cjs');
 const original=global.fetch;
 let handler,saves=0,updates=0,removed=0,stopped=0,rejected=false,failUpdate=false;
 const mainFrame={url:'http://127.0.0.1:37841/connections'},webContents={mainFrame};
 const event={sender:webContents,senderFrame:mainFrame};
 global.fetch=async url=>String(url).includes('/auth/me')?{ok:true,json:async()=>({role:'ADMIN'})}:{ok:!rejected,json:async()=>rejected?{error_code:'INVALID_API_KEYS'}:{link_token:'link-synthetic',hosted_link_url:'https://secure.plaid.com/hl/synthetic'}};
 try{
  registerPlaidIPC({ipcMain:{handle:(_name,callback)=>handler=callback},vault:{load:async()=>values,save:async()=>saves++,remove:async()=>removed++},getBackend:()=>({url:'http://127.0.0.1:12345',token:'private',updatePlaid:async candidate=>{updates++;if(failUpdate)throw new Error('failed');},stop:async()=>stopped++}),getWindow:()=>({isDestroyed:()=>false,webContents}),origin:'http://127.0.0.1:37841'});
  const next={...values,secret:'rotated-secret'};
  assert.equal((await handler(event,{action:'save',token:'jwt',values:next})).ok,false);
  assert.equal(saves,0);assert.equal(updates,0);
  rejected=true;
  assert.equal((await handler(event,{action:'save',token:'jwt',values:{...next,confirmed:true}})).ok,false);
  assert.equal(saves,0);assert.equal(updates,0);
  rejected=false;
  assert.equal((await handler(event,{action:'save',token:'jwt',values:{...next,confirmed:true}})).ok,true);
  assert.equal(saves,1);assert.equal(updates,1);
  assert.equal((await handler(event,{action:'remove',token:'jwt',values:{}})).ok,false);
  assert.equal(removed,0);
  failUpdate=true;
  const result=await handler(event,{action:'remove',token:'jwt',values:{confirmed:true}});
  assert.equal(result.ok,false);assert.match(result.error,/removed.*Restart/);
  assert.equal(removed,1);assert.equal(stopped,1);
 }finally{global.fetch=original}
});
test('maintenance prevents credential mutations before touching the vault',async()=>{
 const {registerPlaidIPC}=require('../plaid.cjs');
 let handler,touched=false;
 const original=global.fetch;
 const mainFrame={url:'http://127.0.0.1:37841/connections'},webContents={mainFrame};
 global.fetch=async()=>({ok:true,json:async()=>({role:'ADMIN'})});
 try{
  const busy=registerPlaidIPC({ipcMain:{handle:(_name,callback)=>handler=callback},vault:{remove:async()=>{touched=true}},getBackend:()=>({url:'http://127.0.0.1:12345',token:'private'}),getWindow:()=>({isDestroyed:()=>false,webContents}),origin:'http://127.0.0.1:37841',canConfigure:()=>false});
  const result=await handler({sender:webContents,senderFrame:mainFrame},{action:'remove',token:'jwt',values:{confirmed:true}});
  assert.equal(result.ok,false);assert.match(result.error,/backup or restore/);assert.equal(touched,false);assert.equal(busy(),false);
 }finally{global.fetch=original}
});
