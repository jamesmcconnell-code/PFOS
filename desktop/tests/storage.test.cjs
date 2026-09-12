const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { storagePaths, LOCAL_SESSION } = require('../storage.cjs');

test('storage is anchored outside app bundles and retains the step-3 profile/session', () => {
  const appData = path.resolve('test-application-support');
  assert.deepEqual(storagePaths(appData), {
    profileDir: path.join(appData, 'PFOS'), dataDir: path.join(appData, 'PFOS', 'data'),
  });
  assert.equal(LOCAL_SESSION, 'persist:pfos-desktop-local');
  assert.throws(() => storagePaths(appData, 'relative-profile'), /absolute/);
});
