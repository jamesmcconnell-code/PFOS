const { test } = require('node:test');
const assert = require('node:assert/strict');
const { backendEnvironment, bundledBackendPath, startBackend } = require('../backend.cjs');

test('runtime environment excludes server settings, credentials, and Python search paths', () => {
  const environment = backendEnvironment();
  for (const name of ['PATH', 'PYTHONPATH', 'DATABASE_URL', 'JWT_SECRET', 'PLAID_SECRET', 'ELECTRON_RUN_AS_NODE']) {
    assert.equal(environment[name], undefined);
  }
});

test('packaged runtime is resolved under application resources', () => {
  assert.match(bundledBackendPath({ isPackaged: true, resourcesPath: '/tmp/resources' }), /resources[/\\]backend[/\\]pfos-api[/\\]pfos-api/);
});

test('missing bundle produces an actionable error rather than running system Python', async () => {
  await assert.rejects(startBackend({ dataDir: '/tmp/unused-pfos', frontendOrigin: 'http://localhost:3000', executable: '/missing-pfos-binary' }), /build:backend/);
});
