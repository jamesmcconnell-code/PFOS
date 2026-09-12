const { test } = require('node:test');
const assert = require('node:assert/strict');
const { localAppURL, isAppNavigation, isExternalURL } = require('../policy.cjs');

test('desktop only accepts a local HTTP origin', () => {
  assert.equal(localAppURL(), 'http://localhost:3000');
  for (const url of ['http://127.0.0.1:3000', 'http://[::1]:3000']) assert.equal(localAppURL(url), url);
  for (const url of ['https://example.com', 'file:///tmp/index.html', 'javascript:alert(1)',
    'http://localhost.evil.test:3000', 'http://user:password@localhost:3000',
    'http://localhost:3000/login', 'http://localhost:3000?next=evil', 'http://localhost:3000/#x']) {
    assert.throws(() => localAppURL(url), undefined, url);
  }
});

test('navigation stays on the chosen origin, including port', () => {
  const origin = localAppURL();
  assert.ok(isAppNavigation(origin + '/transactions?q=hello#details', origin));
  for (const url of ['http://localhost:8000', 'http://127.0.0.1:3000',
    'https://example.com', 'file:///etc/passwd', 'http://user@localhost:3000', 'invalid']) {
    assert.equal(isAppNavigation(url, origin), false, url);
  }
});

test('external links cannot invoke local files or OS protocol handlers', () => {
  assert.ok(isExternalURL('https://example.com/help'));
  for (const url of ['file:///tmp/test', 'javascript:alert(1)', 'data:text/html,test',
    'http://example.com', 'https://user:password@example.com', 'custom-protocol:run', 'invalid']) {
    assert.equal(isExternalURL(url), false, url);
  }
});
