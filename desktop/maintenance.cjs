'use strict';
const {spawn} = require('node:child_process');
const path = require('node:path');
const {backendEnvironment, bundledBackendPath} = require('./backend.cjs');
function runMaintenance({dataDir, operation, file, executable = bundledBackendPath()}) {
  if (!['backup','restore'].includes(operation)) return Promise.reject(new Error('Invalid maintenance operation'));
  return new Promise((resolve, reject) => {
    const child = spawn(executable, ['--data-dir',path.resolve(dataDir),'--maintenance',operation,'--file',path.resolve(file)],
      {env:backendEnvironment(), stdio:['ignore','pipe','pipe'], windowsHide:true});
    let output='', errors='';
    child.stdout.on('data', chunk => {output=(output+chunk).slice(-16000)});
    child.stderr.on('data', chunk => {errors=(errors+chunk).slice(-8000)});
    child.once('error', reject);
    child.once('close', code => {
      if (code !== 0) {reject(new Error(errors.trim() || 'PFOS maintenance failed.')); return;}
      try {resolve(JSON.parse(output))} catch {reject(new Error('Invalid maintenance result'))}
    });
  });
}
module.exports = {runMaintenance};
