'use strict';
const { contextBridge } = require('electron');
const argument = process.argv.find(value => value.startsWith('--pfos-api-url='));
if (argument) {
  const apiBase = argument.slice('--pfos-api-url='.length);
  // The URL is public configuration. The launch capability stays in the main process.
  contextBridge.exposeInMainWorld('pfosDesktop', Object.freeze({ apiBase }));
}
