'use strict';
const { spawn } = require('node:child_process');
const path = require('node:path');
const env = { ...process.env };
// Editors built on Electron may pass this flag to their terminal environment.
// PFOS must launch as a desktop application, not as a Node.js interpreter.
delete env.ELECTRON_RUN_AS_NODE;
const child = spawn(require('electron'), process.argv.slice(2), {
  cwd: path.resolve(__dirname, '..'), env, stdio: 'inherit',
});
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
