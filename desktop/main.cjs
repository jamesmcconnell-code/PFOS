'use strict';

const { app, BrowserWindow, Menu, dialog, shell, nativeImage, session, ipcMain, safeStorage } = require('electron');
const path = require('node:path');
const { startBackend, bundledBackendPath } = require('./backend.cjs');
const { createPlaidVault, registerPlaidIPC } = require('./plaid.cjs');
const { isPlaidCompletion, registerPlaidLinkIPC } = require('./plaid-link.cjs');
const { runMaintenance } = require('./maintenance.cjs');
const { startFrontend, bundledFrontendPath } = require('./frontend.cjs');
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

function menuTemplate(getWindow, origin, { dataDir, backup, restore } = {}) {
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
      ...(backup ? [{label:'Back Up Local Data…', click:backup}, {label:'Restore Local Backup…', click:restore}, {label:'Backup and Migration Guide', click:navigate('/desktop-help')}] : []),
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
  const storage = storagePaths(app.getPath('appData'), userDataPath || app.commandLine.getSwitchValue('user-data-dir') || undefined);
  app.setPath('userData', storage.profileDir);
  let origin;
  try { origin = localAppURL(app.isPackaged ? undefined : process.env.PFOS_DESKTOP_URL); }
  catch (error) { await app.whenReady(); dialog.showErrorBox('PFOS could not start', error.message); app.quit(); return; }
  if (!app.requestSingleInstanceLock()) { app.quit(); return; }
  let window, backend, startup, frontend, maintenance;
  let returnedFromPlaid=false;
  let showRestoreGuide=false;
  app.on('open-url',(event,url)=>{
    event.preventDefault();
    if(!isPlaidCompletion(url))return;
    returnedFromPlaid=true;
    if(backend && !quitting && !maintaining){const target=openWindow();void target.loadApp('/connections');}
  });
  let plaidSettingsBusy=()=>false;
  let maintaining = false;
  let quitting = false, shutdownComplete = false;
  const openWindow = () => {
    if (maintaining || quitting) return;
    if (!window || window.isDestroyed()) {
      window = createWindow(origin, { backend, partition: LOCAL_SESSION });
      void window.loadApp(showRestoreGuide?'/desktop-help?restored=1':returnedFromPlaid?'/connections':'/dashboard');
      showRestoreGuide=false;
    }
    if (window.isMinimized()) window.restore();
    window.show(); window.focus();
    return window;
  };
  app.on('second-instance', () => { if (backend && !quitting) openWindow(); });
  app.on('window-all-closed', () => { if (process.platform !== 'darwin' && !maintaining) app.quit(); });
  app.on('before-quit', event => {
    if (shutdownComplete) return;
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    void (async () => {
      try { await maintenance; const runtime = await startup; await runtime?.stop(); }
      catch { /* Failed startup already cleans up its child process. */ }
      finally { await frontend?.stop(); shutdownComplete = true; app.quit(); }
    })();
  });
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => app.quit());
  await app.whenReady();
  // Isolated verification profiles must not replace the installed app's URL handler.
  if(app.isPackaged && !app.commandLine.hasSwitch('user-data-dir'))app.setAsDefaultProtocolClient('pfos');
  const plaidVault=createPlaidVault(storage.profileDir,safeStorage);
  const localPlaid=()=>plaidVault.load().catch(()=>null);
  startup = (async () => {
    if (app.isPackaged || !process.env.PFOS_DESKTOP_URL) {
      frontend = await startFrontend({directory: bundledFrontendPath({isPackaged: app.isPackaged, resourcesPath: process.resourcesPath})});
      origin = frontend.origin;
    }
    return startBackend({plaid:await localPlaid(),
    dataDir: storage.dataDir, frontendOrigin: origin,
    executable: bundledBackendPath({ isPackaged: app.isPackaged, resourcesPath: process.resourcesPath }),
    onUnexpectedExit: error => {
      if (!quitting) { dialog.showErrorBox('PFOS stopped', error.message); app.quit(); }
    },
  });
  })();
  backend = await startup;
  if (quitting) return;
  plaidSettingsBusy=registerPlaidIPC({ipcMain,vault:plaidVault,getBackend:()=>backend,getWindow:()=>window,origin,canConfigure:()=>!maintaining&&!quitting});
  registerPlaidLinkIPC({ipcMain,getBackend:()=>backend,getWindow:()=>window,origin,openExternal:url=>shell.openExternal(url)});
  app.setAboutPanelOptions({ applicationName: 'PFOS', applicationVersion: app.getVersion(),
    iconPath, comments: 'Personal financial operating system' });
  if (app.dock) app.dock.setIcon(nativeImage.createFromPath(iconPath));
  async function maintain(operation) {
    if (maintaining || quitting) return;
    if(plaidSettingsBusy()){dialog.showErrorBox('Plaid settings are busy','Wait for the Plaid settings operation to finish, then retry backup or restore.');return;}
    openWindow();
    maintaining = true;
    maintenance = (async () => {
      let stopped = false;
      try {
        const filters = [{name:'PFOS local backup', extensions:['pfosbackup']}];
        let file;
        if (operation === 'backup') {
          const result = await dialog.showSaveDialog(window, {title:'Back Up Local Data', filters,
            defaultPath:'PFOS-' + new Date().toISOString().replace(/[:.]/g,'-') + '.pfosbackup',
            message:'Contains financial data, bank/exchange tokens, and their decryption keys. This file is not encrypted. Plaid developer credentials and device preferences are excluded. Save it privately.'});
          if (result.canceled || !result.filePath) return;
          file = result.filePath;
        } else {
          const result = await dialog.showOpenDialog(window, {title:'Restore Local Backup', filters, properties:['openFile']});
          if (result.canceled || !result.filePaths.length) return;
          file = result.filePaths[0];
          const confirmation = await dialog.showMessageBox(window, {type:'warning', buttons:['Cancel','Restore'],
            defaultId:0, cancelId:0, message:'Replace local data with this backup?',
            detail:file + '\nCurrent data will be saved in a recovery copy first. Restore replaces data; it does not merge households. Sign in using an account and password from the backup. This Mac’s Plaid developer credentials are unchanged; a new Mac needs its own Plaid setup.'});
          if (confirmation.response !== 1) return;
        }
        window?.destroy(); window = null;
        await backend.stop(); stopped = true;
        const result = await runMaintenance({dataDir:storage.dataDir, operation, file,
          executable:bundledBackendPath({isPackaged:app.isPackaged, resourcesPath:process.resourcesPath})});
        if (operation === 'restore') {await session.fromPartition(LOCAL_SESSION).clearStorageData({storages:['localstorage']});showRestoreGuide=true;}
        await dialog.showMessageBox({type:'info', message:operation === 'backup'?'Backup saved':'Backup restored',
          detail:operation === 'backup'?result.path+'\nKeep this unencrypted backup private. It does not include this Mac’s Plaid developer credentials.':'Recovery copy: ' + result.path+'\nSign in with the backup’s account and password, review restored data, and check Settings → Plaid before syncing. The backup and migration guide will open next.'});
      } catch (error) {dialog.showErrorBox('PFOS backup / restore', error.message)}
      finally {
        if (stopped && !quitting) {
          startup = startBackend({plaid:await localPlaid(),dataDir:storage.dataDir, frontendOrigin:origin,
            executable:bundledBackendPath({isPackaged:app.isPackaged, resourcesPath:process.resourcesPath}),
            onUnexpectedExit:error => {dialog.showErrorBox('PFOS stopped',error.message); app.quit()}});
          try {backend = await startup} catch (error) {dialog.showErrorBox('PFOS could not reopen',error.message); app.quit()}
        }
        maintaining = false;
        if (!quitting) openWindow();
      }
    })();
    await maintenance;
  }
  Menu.setApplicationMenu(Menu.buildFromTemplate(menuTemplate(openWindow, origin, {...storage,
    backup:()=>void maintain('backup'), restore:()=>void maintain('restore')})));
  openWindow();
  app.on('activate', () => { if (!quitting) openWindow(); });
}

module.exports = { createWindow, menuTemplate, start };
