'use strict';
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const result = spawnSync(process.env.PFOS_BUILD_PYTHON || 'python3', [path.join(__dirname, 'build-backend.py')], { stdio: 'inherit' });
if (result.error) console.error(result.error.message);
process.exitCode = result.status ?? 1;
