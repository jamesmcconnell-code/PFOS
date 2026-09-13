'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const executable = process.env.PFOS_PACKAGED_EXECUTABLE || path.resolve(__dirname,'../dist/mac/PFOS.app/Contents/MacOS/PFOS');
async function waitFor(check) {
  const deadline=Date.now()+45000;
  while(Date.now()<deadline) {
    const result=await check(); if(result) return result;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw new Error('Packaged app did not become ready');
}
async function connect(url) {
  const ws=new WebSocket(url);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
  let id=0;
  const pending=new Map();
  ws.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(pending.has(message.id)) {pending.get(message.id)(message);pending.delete(message.id)}
  };
  return {close:()=>ws.close(), evaluate:async expression=>{
    const request=++id;
    const response=await new Promise(resolve=>{
      pending.set(request,resolve);
      ws.send(JSON.stringify({id:request,method:'Runtime.evaluate',params:{expression,awaitPromise:true,returnByValue:true}}));
    });
    if(response.error || response.result?.exceptionDetails) throw new Error(JSON.stringify(response.error || response.result.exceptionDetails));
    return response.result.result.value;
  }};
}
test('installed macOS application starts without development services and preserves a household across restart', {timeout:150000},async()=>{
  const profile=await fs.mkdtemp(path.join(os.tmpdir(),'pfos-packaged-'));
  try {
    for(const phase of ['create','reopen']) {
      const env={...process.env,PATH:''};
      delete env.ELECTRON_RUN_AS_NODE;
      // Only the verification process enables Chromium debugging.
      const child=spawn(executable,['--user-data-dir='+profile,'--remote-debugging-port=0'],{cwd:profile,env,stdio:['ignore','pipe','pipe']});
      let output='', client, apiBase;
      child.stderr.on('data',chunk=>{output=(output+chunk).slice(-20000)});
      child.stdout.on('data',()=>{});
      const exited=new Promise(resolve=>child.once('close',(code,signal)=>resolve({code,signal})));
      const timeout=setTimeout(()=>child.kill('SIGKILL'),65000);
      try {
        const browserURL=await waitFor(()=>{
          if(child.exitCode!==null) throw new Error('App exited: '+output);
          return output.match(/DevTools listening on (ws:\/\/\S+)/)?.[1];
        });
        const port=new URL(browserURL).port;
        const target=await waitFor(async()=>{
          const pages=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
          return pages.find(page=>page.type==='page' && page.url.startsWith('http://127.0.0.1:37841'));
        });
        client=await connect(target.webSocketDebuggerUrl);
        apiBase=await waitFor(()=>client.evaluate('window.pfosDesktop?.apiBase'));
        const result=await client.evaluate(`(async()=>{
          const api=window.pfosDesktop.apiBase;
          const request=async(route,body)=>{
            const response=await fetch(api+route,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',Authorization:'Bearer '+localStorage.getItem('pfos_token')},...(body?{body:JSON.stringify(body)}:{})});
            if(!response.ok) throw new Error('Request failed '+response.status);
            return response.json();
          };
          if(${JSON.stringify(phase)}==='create') {
            const auth=await request('/auth/register',{email:'packaged@example.com',password:'Packaged-test-123',display_name:'Packaged'});
            localStorage.setItem('pfos_token',auth.access_token);
            await request('/accounts',{name:'Packaged checking',type:'checking',balance:1234.56});
          }
          return {email:(await request('/auth/me')).email,accounts:await request('/accounts')};
        })()`);
        assert.equal(result.email,'packaged@example.com');
        assert.ok(result.accounts.some(account=>account.name==='Packaged checking' && Number(account.balance)===1234.56));
        await client.evaluate("location.href='/accounts/'; true");
        await waitFor(async()=>{
          try {return (await client.evaluate('document.body.innerText')).includes('Packaged checking')} catch {return false}
        });
        client.close(); client=null;
        child.kill('SIGTERM');
        assert.equal((await exited).code,0,output);
        await assert.rejects(fetch(apiBase.replace('/api/v1','/health')));
        await assert.rejects(fetch('http://127.0.0.1:37841'));
      } finally {
        client?.close(); child.kill('SIGTERM'); await exited; clearTimeout(timeout);
      }
    }
  } finally {await fs.rm(profile,{recursive:true,force:true})}
});
