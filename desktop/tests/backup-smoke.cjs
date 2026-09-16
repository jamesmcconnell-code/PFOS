'use strict';
const {app, BrowserWindow, Menu, dialog, safeStorage} = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const {start} = require('../main.cjs');
const {createPlaidVault}=require('../plaid.cjs');
async function waitFor(check) {
  const deadline = Date.now()+30000;
  while (Date.now()<deadline) {
    try {const result = await check(); if (result) return result} catch {}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw new Error('Timed out waiting for backup workflow');
}
async function run() {
  const profile = await fs.mkdtemp(path.join(os.tmpdir(),'pfos-backup-ui-'));
  const file = path.join(profile,'test.pfosbackup');
  const errors = [],messages=[];
  const vault=createPlaidVault(profile,safeStorage);
  dialog.showSaveDialog = async()=>({canceled:false,filePath:file});
  dialog.showOpenDialog = async()=>({canceled:false,filePaths:[file]});
  dialog.showMessageBox = async (...args)=>{messages.push(args.at(-1));return {response:1}};
  // The confirmation has a BrowserWindow first argument; accept the test restore.
  dialog.showErrorBox = (title,message)=>errors.push(title+': '+message);
  delete process.env.PFOS_DESKTOP_URL;
  await start({userDataPath:profile});
  async function ready(previous) {
    return waitFor(async()=>{
      const window = BrowserWindow.getAllWindows()[0];
      if (!window || window===previous) return;
      if (await window.webContents.executeJavaScript('Boolean(window.pfosDesktop)')) return window;
    });
  }
  let window = await ready();
  const credentials = {email:'backup@example.com',password:'Backup-test-123',display_name:'Backup'};
  const call = (win,route,body,token,method)=>win.webContents.executeJavaScript(`(async()=>{
    const response = await fetch(window.pfosDesktop.apiBase+${JSON.stringify(route)}, {
      method:${JSON.stringify(method || (body?'POST':'GET'))},
      headers:{'Content-Type':'application/json',Authorization:'Bearer '+${JSON.stringify(token || '')}},
      ${body?'body:JSON.stringify('+JSON.stringify(body)+'),':''}
    });
    if(!response.ok) throw new Error('API status '+response.status);
    return response.json();
  })()`);
  let token = (await call(window,'/auth/register',credentials)).access_token;
  const menu = label=>Menu.getApplicationMenu().items.find(item=>item.label==='File').submenu.items.find(item=>item.label===label);
  await vault.save({client_id:'synthetic-source',secret:'synthetic-source-secret',environment:'sandbox'});
  menu('Backup and Migration Guide').click();
  await waitFor(()=>window.webContents.executeJavaScript("document.body.innerText.includes('What a backup contains')"));
  menu('Back Up Local Data…').click();
  window = await ready(window);
  await fs.access(file);
  await call(window,'/users/me/theme',{theme_preference:'emerald'},token,'PATCH');
  await vault.save({client_id:'synthetic-destination',secret:'synthetic-destination-secret',environment:'sandbox'});
  const destinationVault=await fs.readFile(path.join(profile,'plaid-credentials.json'),'utf8');
  menu('Restore Local Backup…').click();
  window = await ready(window);
  await waitFor(()=>window.webContents.executeJavaScript("document.body.innerText.includes('Backup restored — next steps')"));
  assert.ok(await window.webContents.executeJavaScript("document.body.innerText.includes('Sign in to review restored connections')"));
  assert.equal(await fs.readFile(path.join(profile,'plaid-credentials.json'),'utf8'),destinationVault);
  assert.equal((await vault.load()).client_id,'synthetic-destination');
  token = (await call(window,'/auth/login',credentials)).access_token;
  assert.notEqual((await call(window,'/auth/me',null,token)).theme_preference,'emerald');
  assert.ok((await fs.readdir(path.join(profile,'data/backups'))).some(name=>name.startsWith('before-restore-')));
  assert.deepEqual(errors,[]);
  assert.ok(messages.some(message=>message.detail?.includes('does not merge households')));
  // Simulate a destination without any local Plaid settings: restoring the same
  // archive must not import the source installation's developer credentials.
  await vault.remove();
  menu('Restore Local Backup…').click();
  window=await ready(window);
  await waitFor(()=>window.webContents.executeJavaScript("document.body.innerText.includes('Backup restored — next steps')"));
  token=(await call(window,'/auth/login',credentials)).access_token;
  await window.webContents.executeJavaScript(`localStorage.setItem('pfos_token',${JSON.stringify(token)});window.dispatchEvent(new Event('focus'))`);
  await waitFor(()=>window.webContents.executeJavaScript("document.body.innerText.includes('Plaid is disabled on this Mac.')"));
  assert.equal(await vault.load(),null);
  assert.equal((await call(window,'/connections/plaid/configuration',null,token)).configured,false);
  // A rejected archive must reopen the unchanged household.
  await fs.writeFile(file,'invalid archive');
  menu('Restore Local Backup…').click();
  window = await ready(window);
  assert.equal((await call(window,'/auth/me',null,token)).email,credentials.email);
  assert.equal(errors.length,1);
  assert.match(errors[0],/zip file/);
  app.once('will-quit',event=>{
    event.preventDefault();
    fs.rm(profile,{recursive:true,force:true}).then(()=>app.exit(0)).catch(error=>{console.error(error);app.exit(1)});
  });
  console.log('Native backup/restore passed: guide, destination credential preservation, no source credential transfer, signed-in missing-key guidance, recovery copy, rejected archive, and API restart.');
  app.quit();
}
setTimeout(()=>{console.error('Backup smoke timed out');app.exit(1)},100000).unref();
run().catch(error=>{console.error(error);app.exit(1)});
