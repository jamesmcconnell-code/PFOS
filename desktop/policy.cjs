'use strict';

function localAppURL(value = 'http://localhost:3000') {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('PFOS_DESKTOP_URL must be a loopback HTTP origin, such as http://localhost:3000');
  }
  return url.origin;
}

function isAppNavigation(value, origin) {
  try {
    const url = new URL(value);
    return url.origin === origin && !url.username && !url.password;
  } catch { return false; }
}

function isExternalURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password;
  } catch { return false; }
}

module.exports = { localAppURL, isAppNavigation, isExternalURL };
