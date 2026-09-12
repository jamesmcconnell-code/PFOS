'use strict';
const { app, dialog } = require('electron');
const { start } = require('./main.cjs');
void start().catch(error => {
  console.error(error);
  dialog.showErrorBox('PFOS could not start', error.message);
  app.exit(1);
});
