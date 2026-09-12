'use strict';
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { start } = require('../main.cjs');
const { localAppURL } = require('../policy.cjs');

async function run() {
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'pfos-app-lifecycle-'));
  process.env.PFOS_DESKTOP_URL = localAppURL(process.env.PFOS_SMOKE_URL);
  await start({ userDataPath: profile });
  const window = BrowserWindow.getAllWindows()[0];
  assert.ok(window, 'Desktop startup did not create its window');
  let apiBase;
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try { apiBase = await window.webContents.executeJavaScript('window.pfosDesktop?.apiBase'); } catch {}
    if (apiBase) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(apiBase, 'Desktop startup did not connect its backend');
  assert.equal((await fetch(apiBase.replace('/api/v1', '/health'))).status, 401);
  app.once('will-quit', event => {
    event.preventDefault();
    void (async () => {
      let alive = false;
      try { await fetch(apiBase.replace('/api/v1', '/health'), { signal: AbortSignal.timeout(1000) }); alive = true; } catch {}
      assert.equal(alive, false, 'API remains active after the app quit sequence');
      console.log('Whole-app lifecycle passed: automatic bundled API startup and graceful shutdown before quit.');
      app.exit(0);
    })().catch(error => { console.error(error); app.exit(1); });
  });
  app.quit();
}
const timeout = setTimeout(() => { console.error('Desktop lifecycle timed out'); app.exit(1); }, 60000);
timeout.unref();
run().catch(error => { console.error(error); app.exit(1); });
