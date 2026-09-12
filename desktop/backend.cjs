'use strict';
const { spawn } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const { localAppURL } = require('./policy.cjs');

function bundledBackendPath({ isPackaged = false, resourcesPath = '' } = {}) {
  return path.join(isPackaged ? resourcesPath : path.join(__dirname, 'resources'),
    'backend', 'pfos-api', process.platform === 'win32' ? 'pfos-api.exe' : 'pfos-api');
}

function backendEnvironment() {
  const env = {};
  for (const key of ['HOME', 'USERPROFILE', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL']) {
    if (process.env[key]) env[key] = process.env[key];
  }
  // No PATH/PYTHONPATH, server DATABASE_URL, provider keys, or inherited secrets.
  return env;
}

async function startBackend({ dataDir, frontendOrigin, executable = bundledBackendPath(), timeoutMs = 60000, onUnexpectedExit = () => {} }) {
  const origin = localAppURL(frontendOrigin);
  await fs.access(executable).catch(() => {
    throw new Error('The bundled PFOS backend is missing. Run npm run build:backend in desktop/ first.');
  });
  await fs.mkdir(dataDir, { recursive: true, mode: 0o700 });
  const token = randomBytes(48).toString('base64url');
  const child = spawn(executable, ['--data-dir', path.resolve(dataDir), '--frontend-origin', origin], {
    cwd: dataDir, env: backendEnvironment(), stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
  });
  let stopped = false, ready = false, exited = false, stopPromise, stderr = '';
  const closed = new Promise(resolve => child.once('close', (code, signal) => {
    exited = true;
    resolve({ code, signal });
    if (ready && !stopped) onUnexpectedExit(new Error('The local PFOS backend stopped unexpectedly. Reopen PFOS to restart it.'));
  }));
  child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-8000); });
  const wait = ms => new Promise(resolve => { const timer = setTimeout(() => resolve(false), ms); timer.unref(); });
  async function stop() {
    if (stopPromise) return stopPromise;
    stopped = true;
    stopPromise = (async () => {
      child.stdin.end();
      if (await Promise.race([closed.then(() => true), wait(5000)])) return;
      child.kill('SIGTERM');
      if (await Promise.race([closed.then(() => true), wait(3000)])) return;
      child.kill('SIGKILL');
      await closed;
    })();
    return stopPromise;
  }
  child.stdin.on('error', () => {}); // Exit-before-bootstrap is reported by close.
  child.stdin.write(JSON.stringify({ token }) + '\n');
  let timeout;
  try {
    const url = await new Promise((resolve, reject) => {
      timeout = setTimeout(() => reject(new Error('The local PFOS backend did not become ready in time.')), timeoutMs);
      let buffer = '';
      child.on('error', error => reject(new Error(`Unable to launch the bundled PFOS backend: ${error.message}`)));
      closed.then(({ code }) => reject(new Error(`PFOS backend startup failed (exit ${code}). ${stderr.trim()}`)));
      child.stdout.on('data', chunk => {
        buffer += chunk;
        if (buffer.length > 16384) { reject(new Error('Invalid PFOS backend startup response')); return; }
        let newline;
        while ((newline = buffer.indexOf('\n')) !== -1) {
          const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1);
          try {
            const message = JSON.parse(line);
            if (message.event !== 'pfos-ready') continue;
            const parsed = new URL(message.url);
            if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || !parsed.port
                || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) {
              throw new Error('Invalid bundled backend address');
            }
            resolve(parsed.origin);
          } catch (error) { reject(error); }
        }
      });
    });
    const response = await fetch(url + '/health', {
      headers: { 'X-PFOS-Desktop-Token': token }, signal: AbortSignal.timeout(5000),
    });
    if (!response.ok || (await response.json()).status !== 'ok' || child.exitCode !== null || child.signalCode !== null || exited || stopped) {
      throw new Error('Bundled backend health check failed');
    }
    ready = true;
    return { url, token, pid: child.pid, stop, closed };
  } catch (error) {
    await stop();
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

module.exports = { bundledBackendPath, backendEnvironment, startBackend };
