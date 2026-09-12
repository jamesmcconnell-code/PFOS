'use strict';

const { app, BrowserWindow, Menu, dialog, shell, nativeImage } = require('electron');
const path = require('node:path');
const { startBackend, bundledBackendPath } = require('./backend.cjs');
const { storagePaths, LOCAL_SESSION } = require('./storage.cjs');
const { localAppURL, isAppNavigation, isExternalURL } = require('./policy.cjs');
const iconPath = path.join(__dirname, 'assets', 'icon.png');
const unavailablePath = path.join(__dirname, 'unavailable.html');

function createWindow(origin, { show = true, partition = 'persist:pfos-desktop', backend } = {}) {
  const window = new BrowserWindow({
    title: 'PFOS', width: 1440, height: 960, minWidth: 900, minHeight: 640,
    backgroundColor: '#0b132b', show: false, icon: iconPath,
    webPreferences: {
      ...(backend ? { preload: path.join(__dirname, 'preload.cjs'),
        additionalArguments: ['--pfos-api-url=' + backend.url + '/api/v1'] } : {}),
      partition, nodeIntegration: false, contextIsolation: true, sandbox: true,
      webSecurity: true, allowRunningInsecureContent: false, webviewTag: false,
      navigateOnDragDrop: false,
    },
  });
  const contents = window.webContents;
  if (backend) {
    contents.session.webRequest.onBeforeSendHeaders({ urls: [backend.url + '/*'] }, (details, callback) => {
      const headers = { ...details.requestHeaders };
      // Never attach the capability to other windows, remote frames, or files.
      for (const key of Object.keys(headers)) if (key.toLowerCase() === 'x-pfos-desktop-token') delete headers[key];
      if (details.webContentsId === contents.id && isAppNavigation(details.frame?.url || '', origin)) {
        headers['X-PFOS-Desktop-Token'] = backend.token;
      }
      callback({ requestHeaders: headers });
    });
  }
  contents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  contents.session.setPermissionCheckHandler(() => false);
  contents.on('will-attach-webview', event => event.preventDefault());
  const protectNavigation = (event, url) => {
    if (!isAppNavigation(url, origin)) event.preventDefault();
  };
  contents.on('will-navigate', protectNavigation);
  contents.on('will-redirect', protectNavigation);
  contents.setWindowOpenHandler(({ url }) => {
    if (isExternalURL(url)) shell.openExternal(url).catch(() => {});
    return { action: 'deny' };
  });
  // Keep Next.js page titles from replacing the application's window title.
  window.on('page-title-updated', event => event.preventDefault());
  window.on('ready-to-show', () => { if (show) window.show(); });
  let loading = false;
  async function loadApp(route = '/dashboard') {
    if (window.isDestroyed() || loading) return;
    loading = true;
    try {
      await window.loadURL(origin + route);
    } catch {
      if (!window.isDestroyed()) await window.loadFile(unavailablePath);
    } finally {
      loading = false;
      if (show && !window.isDestroyed()) window.show();
    }
  }
  // The fallback's fixed retry link carries no renderer-to-main privileges.
  contents.on('will-navigate', (event, url) => {
    if (url === 'https://pfos.invalid/retry') {
      event.preventDefault();
      void loadApp();
    }
  });
  contents.on('render-process-gone', () => {
    if (!window.isDestroyed()) void window.loadFile(unavailablePath).catch(() => {});
  });
  window.loadApp = loadApp;
  return window;
}

function menuTemplate(getWindow, origin, { dataDir } = {}) {
  const navigate = route => () => { const window = getWindow(); if (window) void window.loadApp(route); };
  const reload = () => {
    const window = getWindow();
    if (!window) return;
    const current = window.webContents.getURL();
    const url = isAppNavigation(current, origin) ? new URL(current) : null;
    void window.loadApp(url ? url.pathname + url.search + url.hash : '/dashboard');
  };
  return [
    ...(process.platform === 'darwin' ? [{ label: 'PFOS', submenu: [
      { role: 'about' }, { type: 'separator' }, { role: 'services' }, { type: 'separator' },
      { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' }, { type: 'separator' }, { role: 'quit' },
    ] }] : []),
    { label: 'File', submenu: [
      { label: 'Dashboard', accelerator: 'CmdOrCtrl+1', click: navigate('/dashboard') },
      { label: 'Accounts', accelerator: 'CmdOrCtrl+2', click: navigate('/accounts') },
      { label: 'Transactions', accelerator: 'CmdOrCtrl+3', click: navigate('/transactions') },
      { label: 'Import CSV…', accelerator: 'CmdOrCtrl+I', click: navigate('/import') },
      ...(dataDir ? [{ type: 'separator' }, { label: 'Show Data Folder…', click: async () => {
        try {
          const error = await shell.openPath(dataDir);
          if (error) dialog.showErrorBox('Could not open the PFOS data folder', error);
        } catch (error) { dialog.showErrorBox('Could not open the PFOS data folder', error.message); }
      } }] : []),
      { type: 'separator' }, { role: process.platform === 'darwin' ? 'close' : 'quit' },
    ] },
    { role: 'editMenu' },
    { label: 'View', submenu: [
      { label: 'Reload', accelerator: 'CmdOrCtrl+R', click: reload },
      ...(!app.isPackaged ? [{ role: 'toggleDevTools' }] : []),
      { type: 'separator' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
      { type: 'separator' }, { role: 'togglefullscreen' },
    ] },
    { role: 'windowMenu' },
  ];
}

async function start({ userDataPath } = {}) {
  app.setName('PFOS');
  const storage = storagePaths(app.getPath('appData'), userDataPath);
  app.setPath('userData', storage.profileDir);
  let origin;
  try { origin = localAppURL(process.env.PFOS_DESKTOP_URL); }
  catch (error) { await app.whenReady(); dialog.showErrorBox('PFOS could not start', error.message); app.quit(); return; }
  if (!app.requestSingleInstanceLock()) { app.quit(); return; }
  let window, backend, startup;
  let quitting = false, shutdownComplete = false;
  const openWindow = () => {
    if (!window || window.isDestroyed()) {
      window = createWindow(origin, { backend, partition: LOCAL_SESSION });
      void window.loadApp();
    }
    if (window.isMinimized()) window.restore();
    window.show(); window.focus();
    return window;
  };
  app.on('second-instance', () => { if (backend && !quitting) openWindow(); });
  app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
  app.on('before-quit', event => {
    if (shutdownComplete) return;
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    void (async () => {
      try { const runtime = await startup; await runtime?.stop(); }
      catch { /* Failed startup already cleans up its child process. */ }
      finally { shutdownComplete = true; app.quit(); }
    })();
  });
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => app.quit());
  await app.whenReady();
  startup = startBackend({
    dataDir: storage.dataDir, frontendOrigin: origin,
    executable: bundledBackendPath({ isPackaged: app.isPackaged, resourcesPath: process.resourcesPath }),
    onUnexpectedExit: error => {
      if (!quitting) { dialog.showErrorBox('PFOS stopped', error.message); app.quit(); }
    },
  });
  backend = await startup;
  if (quitting) return;
  app.setAboutPanelOptions({ applicationName: 'PFOS', applicationVersion: app.getVersion(),
    iconPath, comments: 'Personal financial operating system' });
  if (app.dock) app.dock.setIcon(nativeImage.createFromPath(iconPath));
  Menu.setApplicationMenu(Menu.buildFromTemplate(menuTemplate(openWindow, origin, storage)));
  openWindow();
  app.on('activate', () => { if (!quitting) openWindow(); });
}

module.exports = { createWindow, menuTemplate, start };
