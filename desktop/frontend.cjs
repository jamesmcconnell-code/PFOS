'use strict';
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
function bundledFrontendPath({isPackaged = false, resourcesPath} = {}) {
  return isPackaged ? path.join(resourcesPath, 'frontend') : path.join(__dirname, 'resources/frontend');
}
const types = {'.html':'text/html; charset=utf-8', '.js':'text/javascript; charset=utf-8',
  '.css':'text/css; charset=utf-8', '.json':'application/json', '.txt':'text/plain; charset=utf-8',
  '.svg':'image/svg+xml', '.png':'image/png', '.ico':'image/x-icon', '.woff2':'font/woff2', '.woff':'font/woff'};
async function startFrontend({directory = bundledFrontendPath(), port = 37841} = {}) {
  const root = await fs.realpath(directory).catch(() => {
    throw new Error('PFOS interface bundle is missing. Run npm run build:frontend --prefix desktop.');
  });
  await fs.access(path.join(root, 'login/index.html'));
  let origin;
  const server = http.createServer(async (request, response) => {
    try {
      if (request.headers.host !== new URL(origin).host) {response.writeHead(403).end(); return;}
      if (!['GET', 'HEAD'].includes(request.method)) {response.writeHead(405, {Allow:'GET, HEAD'}).end(); return;}
      const pathname = decodeURIComponent(new URL(request.url, origin).pathname);
      if (pathname.includes('\\') || pathname.includes('\0')) {response.writeHead(400).end(); return;}
      let file = path.resolve(root, '.' + pathname);
      if (file !== root && !file.startsWith(root + path.sep)) {response.writeHead(403).end(); return;}
      if ((await fs.stat(file)).isDirectory()) file = path.join(file, 'index.html');
      file = await fs.realpath(file);
      if (!file.startsWith(root + path.sep)) {response.writeHead(403).end(); return;}
      const data = await fs.readFile(file);
      response.writeHead(200, {'Content-Type': types[path.extname(file)] || 'application/octet-stream',
        'X-Content-Type-Options':'nosniff', 'Cache-Control':'no-store'});
      response.end(request.method === 'HEAD' ? undefined : data);
    } catch (error) {
      response.writeHead(error instanceof URIError ? 400 : 404).end();
    }
  });
  await new Promise((resolve, reject) => {
    server.once('error', error => reject(new Error(error.code === 'EADDRINUSE'
      ? 'PFOS needs local port ' + port + '. Close the other app using it and retry.' : error.message)));
    server.listen(port, '127.0.0.1', resolve);
  });
  origin = 'http://127.0.0.1:' + server.address().port;
  return {origin, stop: () => new Promise(resolve => {server.close(resolve); server.closeAllConnections();})};
}
module.exports = {startFrontend, bundledFrontendPath};
