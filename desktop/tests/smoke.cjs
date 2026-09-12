'use strict';
// Real Electron checks use a disposable browser profile and an isolated HTTP fixture.
const { app, BrowserWindow, Menu } = require('electron');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createWindow, menuTemplate } = require('../main.cjs');
const { localAppURL } = require('../policy.cjs');

async function waitFor(check) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Timed out waiting for Electron smoke check');
}

async function run() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'pfos-electron-smoke-'));
  app.setPath('userData', directory);
  app.on('window-all-closed', () => {});
  await app.whenReady();
  let available = true;
  const server = http.createServer((request, response) => {
    if (!available) { request.socket.destroy(); return; }
    response.setHeader('Content-Type', 'text/html');
    response.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'");
    response.end('<!doctype html><html><title>PFOS fixture</title><body><h1>PFOS desktop smoke fixture</h1></body></html>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  let window;
  try {
    window = createWindow(origin, { show: false, partition: 'persist:smoke' });
    await window.loadApp();
    assert.equal(window.webContents.getURL(), origin + '/dashboard');
    const preferences = window.webContents.getLastWebPreferences();
    assert.equal(preferences.sandbox, true);
    assert.equal(preferences.contextIsolation, true);
    assert.equal(preferences.nodeIntegration, false);
    assert.equal(await window.webContents.executeJavaScript('typeof require'), 'undefined');
    await window.webContents.executeJavaScript("localStorage.setItem('pfos_smoke', 'persisted')");
    await window.loadApp('/accounts');
    assert.equal(await window.webContents.executeJavaScript("localStorage.getItem('pfos_smoke')"), 'persisted');
    const menu = Menu.buildFromTemplate(menuTemplate(() => window, origin));
    Menu.setApplicationMenu(menu);
    const file = menu.items.find(item => item.label === 'File');
    file.submenu.items.find(item => item.label === 'Import CSV…').click();
    await waitFor(() => window.webContents.getURL() === origin + '/import');
    await waitFor(() => !window.webContents.isLoading());
    // A renderer-driven navigation must be blocked before it leaves PFOS.
    await window.webContents.executeJavaScript("location.href = 'https://example.invalid/'; undefined");
    await new Promise(resolve => setTimeout(resolve, 200));
    assert.equal(window.webContents.getURL(), origin + '/import');
    await window.webContents.executeJavaScript("window.open('file:///tmp/pfos-smoke-blocked'); undefined");
    assert.equal(BrowserWindow.getAllWindows().length, 1);
    available = false;
    await window.loadApp();
    assert.ok(window.webContents.getURL().startsWith('file:'));
    assert.match(await window.webContents.executeJavaScript('document.body.innerText'), /PFOS couldn’t open/);
    available = true;
    await window.webContents.executeJavaScript("document.querySelector('a').click(); undefined");
    await waitFor(() => window.webContents.getURL() === origin + '/dashboard');
    await waitFor(() => !window.webContents.isLoading());
    window.destroy();
    window = createWindow(origin, { show: false, partition: 'persist:smoke' });
    await window.loadApp();
    assert.equal(await window.webContents.executeJavaScript("localStorage.getItem('pfos_smoke')"), 'persisted');
    if (process.env.PFOS_SMOKE_URL) {
      window.destroy();
      window = createWindow(localAppURL(process.env.PFOS_SMOKE_URL), { show: false, partition: 'smoke-ui' });
      await window.loadApp();
      await waitFor(async () => (await window.webContents.executeJavaScript('document.body.innerText')).includes('Sign in'));
      assert.equal(window.webContents.getURL(), localAppURL(process.env.PFOS_SMOKE_URL) + '/login');
      if (process.env.PFOS_SMOKE_SCREENSHOT) {
        await fs.writeFile(process.env.PFOS_SMOKE_SCREENSHOT, (await window.webContents.capturePage()).toPNG());
      }
    }
    console.log('Electron smoke passed: window, sandbox, menus, navigation, fallback/retry, session, and optional PFOS UI.');
  } finally {
    if (window && !window.isDestroyed()) window.destroy();
    await new Promise(resolve => server.close(resolve));
  }
}
run().then(() => app.exit(0)).catch(error => { console.error(error); app.exit(1); });
