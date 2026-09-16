'use strict';
const {app,BrowserWindow,shell}=require('electron');
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
const assert=require('node:assert/strict');
const {start}=require('../main.cjs');
const realFetch=global.fetch;
let calls=0,opened=[],expectedSecret='synthetic-secret';
let hosted={status:'idle'},verified=false,lastHostedStart='';
const sessionId='11111111-1111-4111-8111-111111111111';
shell.openExternal=async url=>{opened.push(url)};
global.fetch=async(url,init)=>{
  if(String(url).startsWith('https://sandbox.plaid.com/')){
    calls++;const body=JSON.parse(init.body);
    assert.equal(body.client_id,'synthetic-client');assert.equal(body.secret,expectedSecret);
    return new Response(JSON.stringify({link_token:'synthetic-link-token',hosted_link_url:'https://secure.plaid.com/hl/synthetic'}),{status:200,headers:{'Content-Type':'application/json'}});
  }
  if(String(url).includes('/api/v1/connections/plaid/hosted')){
    assert.ok(init.headers.Authorization.startsWith('Bearer '));
    if(new URL(url).pathname.endsWith('/start')){lastHostedStart=String(url);hosted={status:'pending',session_id:sessionId,can_reopen:true,hosted_link_url:'https://secure.plaid.com/hl/synthetic',...(new URL(url).searchParams.has('connection_id')?{mode:'update',target_name:'Existing bank'}:{})};}
    if(String(url).endsWith('/poll') && verified)hosted={status:'complete',mode:hosted.mode,session_id:sessionId,connections:[{id:'synthetic-connection',name:'Synthetic OAuth bank'}]};
    if(String(url).endsWith('/cancel'))hosted={status:'cancelled',session_id:sessionId};
    return new Response(JSON.stringify(hosted),{status:200,headers:{'Content-Type':'application/json'}});
  }
  return realFetch(url,init);
};
async function waitFor(check){const end=Date.now()+30000;while(Date.now()<end){if(await check())return;await new Promise(resolve=>setTimeout(resolve,100))}throw new Error('Plaid UI timed out')}
async function run(){
  const profile=await fs.mkdtemp(path.join(os.tmpdir(),'pfos-plaid-ui-'));
  delete process.env.PFOS_DESKTOP_URL;
  await start({userDataPath:profile});
  const window=BrowserWindow.getAllWindows()[0];
  await waitFor(()=>window.webContents.executeJavaScript('Boolean(window.pfosDesktop?.plaid)'));
  await window.webContents.executeJavaScript(`(async()=>{
    const response=await fetch(window.pfosDesktop.apiBase+'/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'plaid-ui@example.com',password:'Plaid-test-123',display_name:'Local test'})});
    const auth=await response.json();if(!response.ok)throw new Error('Registration failed');localStorage.setItem('pfos_token',auth.access_token);
  })()`);
  await window.loadApp('/connections');
  await waitFor(()=>window.webContents.executeJavaScript(`Boolean([...document.querySelectorAll('button')].find(b=>b.textContent==='Connect a bank with Plaid')?.disabled)`));
  await window.webContents.executeJavaScript(`document.querySelector('[aria-label="Open settings"]').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`Boolean([...document.querySelectorAll('button')].find(b=>b.textContent==='Plaid'))`));
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Plaid').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`Boolean(document.querySelector('[aria-label="Plaid Client ID"]')) && !document.querySelector('fieldset').disabled`));
  await window.webContents.executeJavaScript(`(()=>{
    const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
    for(const [label,value] of [['Plaid Client ID','synthetic-client'],['Plaid secret','synthetic-secret']]){
      const input=document.querySelector('[aria-label="'+label+'"]');setter.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));
    }
  })()`);
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Test connection').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Credentials accepted.')`));
  await assert.rejects(fs.access(path.join(profile,'plaid-credentials.json')));
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Validate and save').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Saved on this computer.')`));
  assert.equal(calls,2);
  const disk=await fs.readFile(path.join(profile,'plaid-credentials.json'),'utf8');
  assert.ok(!disk.includes('synthetic-secret'));
  const status=await window.webContents.executeJavaScript(`window.pfosDesktop.plaid.status(localStorage.getItem('pfos_token'))`);
  assert.equal(status.configured,true);assert.equal(status.secret,undefined);
  const apiStatus=await window.webContents.executeJavaScript(`fetch(window.pfosDesktop.apiBase+'/connections/plaid/configuration',{headers:{Authorization:'Bearer '+localStorage.getItem('pfos_token')}}).then(r=>r.json())`);
  assert.deepEqual(apiStatus,{configured:true,environment:'sandbox'});
  assert.equal(await window.webContents.executeJavaScript(`document.querySelector('[aria-label="Plaid secret"]').value`),'');
  await window.webContents.executeJavaScript(`document.querySelector('[aria-label="Close settings"]').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`Boolean([...document.querySelectorAll('button')].find(b=>b.textContent==='Connect a bank with Plaid'&&!b.disabled))`));
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Connect a bank with Plaid').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Waiting for bank authorization.')`));
  assert.deepEqual(opened,['https://secure.plaid.com/hl/synthetic']);
  assert.equal(await window.webContents.executeJavaScript(`Boolean(document.querySelector('script[src*="cdn.plaid.com"]'))`),false);
  await window.loadApp('/accounts');
  app.emit('open-url',{preventDefault(){}},'pfos://plaid-complete?public_token=forged');
  assert.ok(window.webContents.getURL().includes('/accounts'));
  // A valid return wakes the app, but status stays pending until Plaid verifies it.
  app.emit('open-url',{preventDefault(){}},'pfos://plaid-complete');
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Waiting for bank authorization.')`));
  verified=true;
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Check connection').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Synthetic OAuth bank connected.')`));
  verified=false;
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Connect a bank with Plaid').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`Boolean([...document.querySelectorAll('button')].find(b=>b.textContent==='Cancel linking'&&!b.disabled))`));
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Cancel linking').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Bank linking ended.')`));
  await window.webContents.executeJavaScript(`(()=>{
    window.__originalFetch=window.fetch.bind(window);
    window.fetch=async(input,init)=>{
      if(String(input).endsWith('/api/v1/connections')&&(!init?.method||init.method==='GET'))return new Response(JSON.stringify([{id:'22222222-2222-4222-8222-222222222222',provider:'plaid',name:'Existing bank',plaid_state:'reauthorization_required',reconnect_mode:'update',can_sync:false,plaid_message:'Your bank needs authorization again.'}]),{status:200,headers:{'Content-Type':'application/json'}});
      return window.__originalFetch(input,init);
    };
    window.dispatchEvent(new Event('focus'));
  })()`);
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Bank authorization required')`));
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Manage').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`Boolean([...document.querySelectorAll('button')].find(b=>b.textContent==='Reauthorize bank'))`));
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Reauthorize bank').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Reauthorizing Existing bank')`));
  assert.ok(lastHostedStart.endsWith('?connection_id=22222222-2222-4222-8222-222222222222'));
  verified=true;
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Check connection').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Synthetic OAuth bank reauthorized.')`));
  await window.webContents.executeJavaScript('window.fetch=window.__originalFetch; delete window.__originalFetch');
  verified=false;
  await window.webContents.executeJavaScript(`(async()=>{
    const response=await fetch(window.pfosDesktop.apiBase+'/accounts',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+localStorage.getItem('pfos_token')},body:JSON.stringify({name:'Keep after removal',type:'checking',balance:125})});
    if(!response.ok)throw new Error('Could not seed preserved account');
  })()`);
  await window.webContents.executeJavaScript(`document.querySelector('[aria-label="Open settings"]').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`Boolean([...document.querySelectorAll('button')].find(b=>b.textContent==='Plaid'))`));
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Plaid').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`Boolean(document.querySelector('[aria-label="Plaid secret"]')) && !document.querySelector('fieldset').disabled`));
  await window.webContents.executeJavaScript(`(()=>{const input=document.querySelector('[aria-label="Plaid secret"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'synthetic-rotated-secret');input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Review replacement').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`Boolean(document.querySelector('[aria-label="Replace Plaid credentials"]'))`));
  const before=calls;
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Keep current settings').click()`);
  assert.equal(calls,before);
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Review replacement').click()`);
  expectedSecret='synthetic-rotated-secret';
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Validate and replace').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Saved on this computer.') && !document.querySelector('[aria-label="Replace Plaid credentials"]')`));
  assert.equal(calls,before+1);
  assert.ok(!(await fs.readFile(path.join(profile,'plaid-credentials.json'),'utf8')).includes(expectedSecret));
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Remove Plaid credentials').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`Boolean(document.querySelector('[aria-label="Remove Plaid credentials"]'))`));
  await window.webContents.executeJavaScript(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Confirm removal').click()`);
  await waitFor(()=>window.webContents.executeJavaScript(`document.body.innerText.includes('Plaid credentials removed from this computer.')`));
  await assert.rejects(fs.access(path.join(profile,'plaid-credentials.json')));
  const removed=await window.webContents.executeJavaScript(`(async()=>{const headers={Authorization:'Bearer '+localStorage.getItem('pfos_token')};const api=window.pfosDesktop.apiBase;return {config:await fetch(api+'/connections/plaid/configuration',{headers}).then(r=>r.json()),accounts:await fetch(api+'/accounts',{headers}).then(r=>r.json())}})()`);
  assert.equal(removed.config.configured,false);
  assert.ok(removed.accounts.some(account=>account.name==='Keep after removal'&&Number(account.balance)===125));
  app.once('will-quit',event=>{event.preventDefault();fs.rm(profile,{recursive:true,force:true}).then(()=>app.exit(0)).catch(()=>app.exit(1))});
  console.log('Plaid desktop passed: real Keychain storage, browser handoff, callback validation, verified completion, navigation recovery, cancellation, reviewed secret replacement, and credential removal with financial data preserved. Plaid HTTPS and Hosted Link API results/browser opening were mocked.');
  app.quit();
}
setTimeout(()=>{console.error('Plaid settings test timed out');app.exit(1)},100000).unref();
run().catch(async error=>{console.error(error);const window=BrowserWindow.getAllWindows()[0];if(window)console.error(await window.webContents.executeJavaScript('document.body.innerText'));app.once('will-quit',event=>{event.preventDefault();app.exit(1)});app.quit()});
