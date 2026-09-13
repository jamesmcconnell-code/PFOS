'use strict';
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const frontend = path.resolve(__dirname, '../../frontend');
const output = path.resolve(__dirname, '../resources/frontend');
const next = require.resolve('next/dist/bin/next', {paths: [frontend]});
const result = spawnSync(process.execPath, [next, 'build'], {
  cwd: frontend, stdio: 'inherit', env: {...process.env, PFOS_DESKTOP_BUILD: '1'},
});
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status || 1);
fs.accessSync(path.join(frontend, 'out/login/index.html'));
fs.rmSync(output, {recursive: true, force: true});
fs.cpSync(path.join(frontend, 'out'), output, {recursive: true});
console.log('PFOS interface bundled at ' + output);
