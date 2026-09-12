'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { spawn } = require('node:child_process');
const { startBackend, bundledBackendPath } = require('../backend.cjs');
const origin = 'http://localhost:3000';

async function temporary() { return fs.mkdtemp(path.join(os.tmpdir(), 'pfos-bundle-test-')); }
async function waitFor(check) {
  const end = Date.now() + 15000;
  while (Date.now() < end) {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Timed out waiting for bundled backend cleanup');
}

test('replacing the app bundle preserves local finances, settings, and secrets without Python/PATH', { timeout: 90000 }, async () => {
  const directory = await temporary();
  const bundle = path.join(directory, 'relocated-runtime');
  await fs.cp(path.dirname(bundledBackendPath()), bundle, { recursive: true, verbatimSymlinks: true });
  let executable = path.join(bundle, path.basename(bundledBackendPath()));
  const dataDir = path.join(directory, 'household');
  await fs.mkdir(dataDir);
  const unwanted = path.join(directory, 'must-not-exist.db');
  await fs.writeFile(path.join(dataDir, '.env'), `DATABASE_URL=sqlite:///${unwanted}\nJWT_SECRET=inherited-server-secret\n`);
  let runtime;
  const credentials = { email: 'bundled@example.com', password: 'Bundled-test-123' };
  try {
    runtime = await startBackend({ executable, dataDir, frontendOrigin: origin });
    assert.equal((await fetch(runtime.url + '/health')).status, 401);
    assert.equal((await fetch(runtime.url + '/health', { headers: { 'X-PFOS-Desktop-Token': runtime.token, Origin: 'https://untrusted.example' } })).status, 403);
    const headers = { 'Content-Type': 'application/json', 'X-PFOS-Desktop-Token': runtime.token };
    const api = async (route, body) => {
      const response = await fetch(runtime.url + '/api/v1' + route, { headers, method: body ? 'POST' : 'GET', ...(body ? { body: JSON.stringify(body) } : {}) });
      assert.ok(response.ok, await response.clone().text());
      return response.json();
    };
    headers.Authorization = 'Bearer ' + (await api('/auth/register', { ...credentials, display_name: 'Bundled' })).access_token;
    const settingResponse = await fetch(runtime.url + '/api/v1/household/financial-settings', {
      method: 'PATCH', headers, body: JSON.stringify({ checking_account_ceiling: 1234.56 }),
    });
    assert.equal(settingResponse.status, 200);
    const themeResponse = await fetch(runtime.url + '/api/v1/users/me/theme', {
      method: 'PATCH', headers, body: JSON.stringify({ theme_preference: 'emerald' }),
    });
    assert.equal(themeResponse.status, 200);
    const account = await api('/accounts', { name: 'Bundled checking', type: 'checking', balance: 0 });
    const today = new Date().toISOString().slice(0, 10);
    for (const expected of [3, 0]) {
      const form = new FormData();
      form.append('file', new Blob([`date,description,amount\n${today},Paycheck,1000.25\n${today},Groceries,-42.37\n${today},Small purchase,-0.10\n`]), 'statement.csv');
      const response = await fetch(runtime.url + '/api/v1/connections/csv/' + account.id,
        { method: 'POST', headers: { Authorization: headers.Authorization, 'X-PFOS-Desktop-Token': runtime.token }, body: form });
      assert.ok(response.ok, await response.clone().text());
      assert.equal((await response.json()).imported, expected);
    }
    const dashboard = await api('/dashboard');
    assert.equal(dashboard.monthly_income, 1000.25);
    assert.equal(dashboard.monthly_expenses, 42.47);
    assert.equal(dashboard.monthly_savings, 957.78);
    await assert.rejects(startBackend({ executable, dataDir, frontendOrigin: origin }), /already open/);
    const secretsBefore = await fs.readFile(path.join(dataDir, 'runtime.json'), 'utf8');
    const oldToken = runtime.token;
    await runtime.stop();
    assert.equal((await runtime.closed).code, 0);
    // Remove the old application completely, then install a replacement in a new
    // resources directory while preserving the independent household directory.
    await fs.rm(bundle, { recursive: true, force: true });
    const resourcesPath = path.join(directory, 'replacement-app', 'resources');
    executable = bundledBackendPath({ isPackaged: true, resourcesPath });
    await fs.cp(path.dirname(bundledBackendPath()), path.dirname(executable), { recursive: true, verbatimSymlinks: true });
    runtime = await startBackend({ executable, dataDir, frontendOrigin: origin });
    assert.equal((await fetch(runtime.url + '/health', { headers: { 'X-PFOS-Desktop-Token': oldToken } })).status, 401);
    headers['X-PFOS-Desktop-Token'] = runtime.token;
    headers.Authorization = 'Bearer ' + (await api('/auth/login', credentials)).access_token;
    assert.equal((await api('/dashboard')).monthly_savings, dashboard.monthly_savings);
    assert.equal((await api('/household/financial-settings')).checking_account_ceiling, 1234.56);
    assert.equal((await api('/auth/me')).theme_preference, 'emerald');
    assert.equal(await fs.readFile(path.join(dataDir, 'runtime.json'), 'utf8'), secretsBefore);
    await assert.rejects(fs.access(unwanted));
    if (process.platform !== 'win32') assert.equal((await fs.stat(path.join(dataDir, 'runtime.json'))).mode & 0o777, 0o600);
  } finally { await runtime?.stop(); await fs.rm(directory, { recursive: true, force: true }); }
});

test('backend exits when its owning process disappears', { timeout: 45000 }, async () => {
  const dataDir = await temporary();
  const owner = spawn(process.execPath, ['-e', `
    const { startBackend } = require(${JSON.stringify(path.resolve(__dirname, '../backend.cjs'))});
    startBackend({dataDir:process.argv[1],frontendOrigin:'http://localhost:3000'})
      .then(runtime => console.log(JSON.stringify({url:runtime.url})))
      .catch(error => { console.error(error); process.exit(1); });
  `, dataDir], { stdio: ['ignore', 'pipe', 'pipe'] });
  let url;
  try {
    url = await new Promise((resolve, reject) => {
      let buffer = '';
      owner.stdout.on('data', chunk => {
        buffer += chunk;
        if (buffer.includes('\n')) resolve(JSON.parse(buffer.split('\n')[0]).url);
      });
      owner.on('error', reject);
      owner.on('exit', code => reject(new Error('Owner exited before backend startup: ' + code)));
    });
    assert.equal((await fetch(url + '/health')).status, 401);
    owner.kill('SIGKILL');
    await waitFor(async () => {
      try { await fetch(url + '/health', { signal: AbortSignal.timeout(500) }); return false; }
      catch { return true; }
    });
  } finally { owner.kill('SIGKILL'); await fs.rm(dataDir, { recursive: true, force: true }); }
});

test('startup timeout terminates the owned backend', { timeout: 20000 }, async () => {
  const dataDir = await temporary();
  try {
    await assert.rejects(startBackend({ dataDir, frontendOrigin: origin, timeoutMs: 1 }), /ready in time/);
    // Acquiring the same storage lock again proves no timed-out backend remains.
    const runtime = await startBackend({ dataDir, frontendOrigin: origin });
    await runtime.stop();
  } finally { await fs.rm(dataDir, { recursive: true, force: true }); }
});

test('unexpected backend exit is reported to its owner', { timeout: 20000 }, async () => {
  const dataDir = await temporary();
  let runtime, failure;
  try {
    runtime = await startBackend({ dataDir, frontendOrigin: origin, onUnexpectedExit: error => { failure = error; } });
    process.kill(runtime.pid, 'SIGKILL');
    await runtime.closed;
    assert.match(failure.message, /stopped unexpectedly/);
  } finally { await runtime?.stop(); await fs.rm(dataDir, { recursive: true, force: true }); }
});


test('missing initialized database is reported without creating an empty replacement', { timeout: 30000 }, async () => {
  const dataDir = await temporary();
  let runtime;
  try {
    runtime = await startBackend({ dataDir, frontendOrigin: origin });
    await runtime.stop();
    const secrets = await fs.readFile(path.join(dataDir, 'runtime.json'), 'utf8');
    assert.equal(JSON.parse(secrets).database_initialized, true);
    const database = path.join(dataDir, 'pfos.db');
    await fs.rename(database, path.join(dataDir, 'saved-original.db'));
    await assert.rejects(startBackend({ dataDir, frontendOrigin: origin }), /missing or empty/);
    await assert.rejects(fs.access(database));
    assert.equal(await fs.readFile(path.join(dataDir, 'runtime.json'), 'utf8'), secrets);
    await fs.rename(path.join(dataDir, 'saved-original.db'), database);
    runtime = await startBackend({ dataDir, frontendOrigin: origin });
    await runtime.stop();
  } finally { await runtime?.stop(); await fs.rm(dataDir, { recursive: true, force: true }); }
});
