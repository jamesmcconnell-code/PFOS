'use strict';
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { startBackend } = require('../backend.cjs');
const { createWindow } = require('../main.cjs');
const { startFrontend } = require('../frontend.cjs');
const { localAppURL } = require('../policy.cjs');

async function waitFor(check) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Timed out waiting for PFOS UI');
}

async function run() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'pfos-bundled-ui-'));
  app.setPath('userData', directory);
  app.on('window-all-closed', () => {});
  await app.whenReady();
  const frontend = process.env.PFOS_SMOKE_URL ? null : await startFrontend({port:0});
  const origin = frontend?.origin || localAppURL(process.env.PFOS_SMOKE_URL);
  let runtime, window;
  try {
    runtime = await startBackend({ dataDir: path.join(directory, 'data'), frontendOrigin: origin });
    window = createWindow(origin, { show: false, partition: 'persist:bundled-smoke', backend: runtime });
    await window.loadApp('/login');
    assert.equal(await window.webContents.executeJavaScript('window.pfosDesktop.apiBase'), runtime.url + '/api/v1');
    assert.equal(await window.webContents.executeJavaScript('typeof require'), 'undefined');
    assert.deepEqual(await window.webContents.executeJavaScript('Object.keys(window.pfosDesktop)'), ['apiBase']);
    await waitFor(async () => (await window.webContents.executeJavaScript('document.body.innerText')).includes('Welcome to PFOS'));
    await window.webContents.executeJavaScript(`(() => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      for (const [id, value] of Object.entries({name:'Desktop bundle',email:'electron-bundle@example.com',password:'Desktop-bundle-123',confirm:'wrong-password'})) {
        const input = document.getElementById(id); setter.call(input, value);
        input.dispatchEvent(new Event('input', {bubbles:true}));
      }
    })()`);
    await window.webContents.executeJavaScript('document.querySelector("form").requestSubmit()');
    await waitFor(async () => (await window.webContents.executeJavaScript('document.body.innerText')).includes('Passwords do not match'));
    await window.webContents.executeJavaScript(`(() => {
      const input = document.getElementById('confirm');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input,'Desktop-bundle-123');
      input.dispatchEvent(new Event('input', {bubbles:true}));
    })()`);
    await window.webContents.executeJavaScript('document.querySelector("form").requestSubmit()');
    await waitFor(async () => window.webContents.getURL().includes('/dashboard'));
    await window.loadApp('/login');
    await waitFor(async () => (await window.webContents.executeJavaScript('document.body.innerText')).includes('Sign in to your household saved on this computer.'));
    assert.equal(await window.webContents.executeJavaScript('Boolean(document.getElementById("confirm"))'), false);
    const result = await window.webContents.executeJavaScript(`(async () => {
      const base = window.pfosDesktop.apiBase;
      const auth = {access_token:localStorage.getItem('pfos_token')};
      const headers = {'Content-Type':'application/json',Authorization:'Bearer '+auth.access_token};
      const accountResponse = await fetch(base+'/accounts',{method:'POST',headers,body:JSON.stringify({name:'Bundled checking',type:'checking',balance:0})});
      const account = await accountResponse.json();
      if (!accountResponse.ok) throw new Error(JSON.stringify(account));
      const form = new FormData(); const today = new Date().toISOString().slice(0,10);
      form.append('file',new Blob(['date,description,amount\\n'+today+',Paycheck,1000.25\\n'+today+',Groceries,-42.47\\n']),'statement.csv');
      const imported = await fetch(base+'/connections/csv/'+account.id,{method:'POST',headers:{Authorization:headers.Authorization},body:form});
      return {status:imported.status,body:await imported.json()};
    })()`);
    assert.equal(result.status, 200, JSON.stringify(result));
    assert.equal(result.body.imported, 2);
    console.log('Bundled renderer registration and import passed.');
    await window.loadApp('/dashboard');
    await waitFor(async () => await window.webContents.executeJavaScript(`Boolean(document.querySelector('a[href="/accounts/"], a[href="/accounts"]'))`));
    await window.webContents.executeJavaScript(`document.querySelector('a[href="/accounts/"], a[href="/accounts"]').click()`);
    await waitFor(async () => (await window.webContents.executeJavaScript('document.body.innerText')).includes('Bundled checking'));
    await window.loadApp('/import');
    await waitFor(async () => (await window.webContents.executeJavaScript('document.body.innerText')).includes('Bundled checking'));
    await window.loadApp('/dashboard');
    await waitFor(async () => (await window.webContents.executeJavaScript('document.body.innerText')).includes('957.78'));
    // Another Electron window sharing the session does not receive the launch capability.
    const outsider = new BrowserWindow({ show: false, webPreferences: { partition: 'persist:bundled-smoke', sandbox: true, contextIsolation: true } });
    try {
      await outsider.loadURL(origin + '/login');
      const denied = await outsider.webContents.executeJavaScript(`fetch(${JSON.stringify(runtime.url + '/api/v1/accounts')}).then(r=>r.status).catch(()=>'blocked')`);
      assert.ok(denied === 401 || denied === 'blocked', 'Unrelated window reached the private API');
    } finally { outsider.destroy(); }
    console.log('Bundled Electron smoke passed: preload URL, protected API, registration, CSV import, and actual accounts/import/dashboard screens.');
  } finally {
    if (window && !window.isDestroyed()) window.destroy();
    await runtime?.stop();
    await frontend?.stop();
  }
}
run().then(() => app.exit(0)).catch(error => { console.error(error); app.exit(1); });
