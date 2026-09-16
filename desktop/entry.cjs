'use strict';
const { app, dialog } = require('electron');
const path = require('node:path');
const { start } = require('./main.cjs');
const { runMaintenance } = require('./maintenance.cjs');
const { bundledBackendPath } = require('./backend.cjs');
void start().catch(async error => {
  console.error(error);
  await app.whenReady();
  const choice = await dialog.showMessageBox({type:'error', message:'PFOS could not start',
    detail:error.message, buttons:['Quit','Restore Local Backup…'], defaultId:0, cancelId:0});
  if (choice.response === 1) {
    const selected = await dialog.showOpenDialog({title:'Restore Local Backup', properties:['openFile'],
      filters:[{name:'PFOS local backup',extensions:['pfosbackup']}]});
    if (!selected.canceled && selected.filePaths.length) {
      const confirm = await dialog.showMessageBox({type:'warning', message:'Replace local data with this backup?',
        detail:selected.filePaths[0]+'\nCurrent files will be preserved in a recovery copy first. Restore replaces data; it does not merge households. Sign in with an account and password from the backup. This Mac’s Plaid developer credentials are unchanged.',
        buttons:['Cancel','Restore'], defaultId:0, cancelId:0});
      if (confirm.response === 1) {
        try {
          const result = await runMaintenance({dataDir:path.join(app.getPath('userData'),'data'),
            operation:'restore',file:selected.filePaths[0],
            executable:bundledBackendPath({isPackaged:app.isPackaged,resourcesPath:process.resourcesPath})});
          const {session} = require('electron');
          const {LOCAL_SESSION} = require('./storage.cjs');
          await session.fromPartition(LOCAL_SESSION).clearStorageData({storages:['localstorage']});
          await dialog.showMessageBox({message:'Backup restored. PFOS will restart.',detail:'Recovery copy: '+result.path+'\nAfter restarting, sign in with the backup’s account and password. Open File → Backup and Migration Guide for Plaid setup and restored-bank checks.'});
          app.relaunch();
        } catch (failure) {dialog.showErrorBox('Unable to restore backup',failure.message)}
      }
    }
  }
  app.quit();
}).catch(error=>{console.error(error); app.exit(1)});
