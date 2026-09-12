'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
test('login and browser preferences survive a complete Electron restart', { timeout: 100000 }, async () => {
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'pfos-storage-test-'));
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/html' });
    response.end('<!doctype html><title>PFOS storage test</title><p>Temporary test profile</p>');
  });
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    for (const phase of ['write', 'read']) {
      const env = { ...process.env, PFOS_TEST_PROFILE: profile, PFOS_TEST_PHASE: phase,
        PFOS_DESKTOP_URL: 'http://127.0.0.1:' + server.address().port };
      delete env.ELECTRON_RUN_AS_NODE;
      await new Promise((resolve, reject) => {
        const child = spawn(require('electron'), [path.join(__dirname, 'storage-process.cjs')], { env, stdio: ['ignore', 'pipe', 'pipe'] });
        let output = '';
        child.stdout.on('data', chunk => { output += chunk; });
        child.stderr.on('data', chunk => { output += chunk; });
        const timer = setTimeout(() => child.kill('SIGKILL'), 45000);
        child.once('error', error => { clearTimeout(timer); reject(error); });
        child.once('exit', (code, signal) => {
          clearTimeout(timer);
          try { assert.equal(code, 0, 'Electron failed (' + signal + '): ' + output);
            assert.ok(output.includes('Persistence phase passed: ' + phase), output); resolve();
          } catch (error) { reject(error); }
        });
      });
    }
  } finally {
    await new Promise(resolve => server.close(resolve));
    await fs.rm(profile, { recursive: true, force: true });
  }
});
