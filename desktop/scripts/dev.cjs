'use strict';
// Own both child processes so exiting development also stops the Next.js server.
const { spawn } = require('node:child_process');
const path = require('node:path');
const net = require('node:net');
const { localAppURL } = require('../policy.cjs');
const origin = localAppURL(process.env.PFOS_DESKTOP_URL);
const url = new URL(origin);
const port = Number(url.port || 80);
const host = url.hostname.replace(/^\[|\]$/g, '');
const children = new Set();
let stopping = false;
function stop(code) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill('SIGTERM');
  const timer = setTimeout(() => {
    for (const child of children) child.kill('SIGKILL');
  }, 10000);
  timer.unref();
  process.exitCode = code;
}
function launch(executable, args, options = {}) {
  const child = spawn(executable, args, { stdio: 'inherit', ...options });
  children.add(child);
  child.on('error', error => { console.error(error.message); stop(1); });
  child.on('exit', code => { children.delete(child); stop(code ?? 1); });
  return child;
}
async function main() {
  // Fail if the port is occupied; do not attach silently to a different project.
  await new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', reject);
    probe.listen(port, host, () => probe.close(resolve));
  });
  const frontend = path.resolve(__dirname, '../../frontend');
  const next = require.resolve('next/dist/bin/next', { paths: [frontend] });
  launch(process.execPath, [next, 'dev', '--hostname', host, '--port', String(port)], { cwd: frontend });
  const deadline = Date.now() + 90000;
  while (!stopping && Date.now() < deadline) {
    try {
      const response = await fetch(origin + '/login', { signal: AbortSignal.timeout(3000) });
      if (response.ok) {
        const env = { ...process.env, PFOS_DESKTOP_URL: origin };
        delete env.ELECTRON_RUN_AS_NODE;
        launch(require('electron'), [path.resolve(__dirname, '..')], { env });
        return;
      }
    } catch { /* Next.js may still be compiling. */ }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  if (!stopping) { console.error('PFOS frontend did not become ready within 90 seconds.'); stop(1); }
}
process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));
main().catch(error => {
  console.error(`Unable to start PFOS: ${error.message}\nIf PFOS is already running on this port, use npm start instead.`);
  stop(1);
});
