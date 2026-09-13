'use strict';
const {app, BrowserWindow, Menu, dialog} = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const {start} = require('../main.cjs');
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
  const errors = [];
  dialog.showSaveDialog = async()=>({canceled:false,filePath:file});
  dialog.showOpenDialog = async()=>({canceled:false,filePaths:[file]});
  dialog.showMessageBox = async options=>({response:1});
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
  menu('Back Up Local Data…').click();
  window = await ready(window);
  await fs.access(file);
  await call(window,'/users/me/theme',{theme_preference:'emerald'},token,'PATCH');
  menu('Restore Local Backup…').click();
  window = await ready(window);
  token = (await call(window,'/auth/login',credentials)).access_token;
  assert.notEqual((await call(window,'/auth/me',null,token)).theme_preference,'emerald');
  assert.ok((await fs.readdir(path.join(profile,'data/backups'))).some(name=>name.startsWith('before-restore-')));
  assert.deepEqual(errors,[]);
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
  console.log('Native backup/restore passed: menu actions, frozen maintenance, recovery copy, data restored, API reopened.');
  app.quit();
}
setTimeout(()=>{console.error('Backup smoke timed out');app.exit(1)},100000).unref();
run().catch(error=>{console.error(error);app.exit(1)});
