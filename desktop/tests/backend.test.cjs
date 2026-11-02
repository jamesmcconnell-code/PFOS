const { test } = require('node:test');
const assert = require('node:assert/strict');
const { backendEnvironment, bundledBackendPath, startBackend } = require('../backend.cjs');

test('runtime environment excludes server settings, credentials, and Python search paths', () => {
  const environment = backendEnvironment();
  for (const name of ['PATH', 'PYTHONPATH', 'DATABASE_URL', 'JWT_SECRET', 'PLAID_SECRET', 'ELECTRON_RUN_AS_NODE']) {
    assert.equal(environment[name], undefined);
  }
});

test('runtime passes only the opt-in Ollama settings as additional configuration', () => {
  const names = ['PFOS_OLLAMA_ENABLED', 'PFOS_OLLAMA_MODEL', 'DATABASE_URL', 'PLAID_SECRET'];
  const previous = Object.fromEntries(names.map(name => [name, process.env[name]]));
  try {
    process.env.PFOS_OLLAMA_ENABLED = 'true';
    process.env.PFOS_OLLAMA_MODEL = 'qwen2.5:7b';
    process.env.DATABASE_URL = 'postgresql://must-not-pass';
    process.env.PLAID_SECRET = 'must-not-pass';
    const environment = backendEnvironment();
    assert.equal(environment.PFOS_OLLAMA_ENABLED, 'true');
    assert.equal(environment.PFOS_OLLAMA_MODEL, 'qwen2.5:7b');
    assert.equal(environment.DATABASE_URL, undefined);
    assert.equal(environment.PLAID_SECRET, undefined);
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});

test('packaged runtime is resolved under application resources', () => {
  assert.match(bundledBackendPath({ isPackaged: true, resourcesPath: '/tmp/resources' }), /resources[/\\]backend[/\\]pfos-api[/\\]pfos-api/);
});

test('missing bundle produces an actionable error rather than running system Python', async () => {
  await assert.rejects(startBackend({ dataDir: '/tmp/unused-pfos', frontendOrigin: 'http://localhost:3000', executable: '/missing-pfos-binary' }), /build:backend/);
});
