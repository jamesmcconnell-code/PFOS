'use strict';
const { app, BrowserWindow, Menu } = require('electron');
const assert = require('node:assert/strict');
const { start } = require('../main.cjs');
async function run() {
  await start({ userDataPath: process.env.PFOS_TEST_PROFILE });
  const window = BrowserWindow.getAllWindows()[0];
  assert.ok(window);
  const deadline = Date.now() + 20000;
  while (!(await window.webContents.executeJavaScript('Boolean(window.pfosDesktop)'))) {
    assert.ok(Date.now() < deadline, 'Preload did not become ready');
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(Menu.getApplicationMenu().items.find(item => item.label === 'File')
    .submenu.items.some(item => item.label === 'Show Data Folder…'));
  const result = await window.webContents.executeJavaScript(`(async () => {
    const api = window.pfosDesktop.apiBase;
    if (${JSON.stringify(process.env.PFOS_TEST_PHASE)} === 'write') {
      const response = await fetch(api + '/auth/register', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
          email: 'restart@example.com', password: 'Restart-test-123', display_name: 'Restart'
        }) });
      if (!response.ok) throw new Error('Registration failed: ' + response.status);
      localStorage.setItem('pfos_token', (await response.json()).access_token);
      localStorage.setItem('pfos_restart_marker', 'saved-preference');
    }
    const token = localStorage.getItem('pfos_token');
    const response = await fetch(api + '/auth/me', { headers: { Authorization: 'Bearer ' + token } });
    return { status: response.status, email: (await response.json()).email,
      marker: localStorage.getItem('pfos_restart_marker') };
  })()`);
  assert.deepEqual(result, { status: 200, email: 'restart@example.com', marker: 'saved-preference' });
  window.webContents.session.flushStorageData();
  console.log('Persistence phase passed: ' + process.env.PFOS_TEST_PHASE);
  app.quit();
}
setTimeout(() => { console.error('Persistence process timed out'); app.exit(1); }, 45000).unref();
run().catch(error => { console.error(error); app.exit(1); });
