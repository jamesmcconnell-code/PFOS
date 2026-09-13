'use strict';
const http = require('node:http');
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const {startFrontend} = require('../frontend.cjs');
test('bundled interface serves routes and assets, rejects foreign hosts and escaping files, and closes its port', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'pfos-frontend-'));
  let server;
  try {
    await fs.mkdir(path.join(root, 'login'));
    await fs.writeFile(path.join(root, 'login/index.html'), '<h1>Welcome</h1>');
    await fs.writeFile(path.join(root, 'app.js'), 'void 0;');
    await fs.symlink(path.join(root, '..'), path.join(root, 'escape'));
    server = await startFrontend({directory:root, port:0});
    assert.equal(await (await fetch(server.origin+'/login')).text(), '<h1>Welcome</h1>');
    assert.match((await fetch(server.origin+'/app.js')).headers.get('content-type'), /javascript/);
    assert.equal((await fetch(server.origin+'/missing')).status, 404);
    assert.equal((await fetch(server.origin+'/login', {method:'POST'})).status, 405);
    const foreignStatus = await new Promise((resolve, reject) => {
      http.get(server.origin+'/login', {headers:{Host:'untrusted.example'}}, response => {
        response.resume(); resolve(response.statusCode);
      }).on('error', reject);
    });
    assert.equal(foreignStatus, 403);
    assert.equal((await fetch(server.origin+'/escape/'+path.basename(root)+'/app.js')).status, 200);
    // A symlink to an actual outside file may never be served.
    await fs.symlink(__filename, path.join(root, 'outside.js'));
    assert.equal((await fetch(server.origin+'/outside.js')).status, 403);
    await assert.rejects(startFrontend({directory:root, port:Number(new URL(server.origin).port)}), /Close the other app/);
    await server.stop();
    await assert.rejects(fetch(server.origin));
    server = null;
  } finally {await server?.stop(); await fs.rm(root,{recursive:true,force:true});}
});
