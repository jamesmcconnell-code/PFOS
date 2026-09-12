'use strict';
const path = require('node:path');

// These names are a storage contract, independent of the executable path,
// display name, release version, or development/packaged mode. Preserve them.
const PROFILE_FOLDER = 'PFOS';
const LOCAL_SESSION = 'persist:pfos-desktop-local';

function storagePaths(appData, profileOverride) {
  const profileDir = profileOverride || path.join(appData, PROFILE_FOLDER);
  if (!path.isAbsolute(profileDir)) throw new Error('PFOS storage requires an absolute profile path');
  return Object.freeze({ profileDir, dataDir: path.join(profileDir, 'data') });
}

module.exports = { storagePaths, LOCAL_SESSION };
