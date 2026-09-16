'use strict';
const { contextBridge, ipcRenderer } = require('electron');
const argument = process.argv.find(value => value.startsWith('--pfos-api-url='));
if (argument) {
  const apiBase = argument.slice('--pfos-api-url='.length);
  // The URL is public configuration. The launch capability stays in the main process.
  contextBridge.exposeInMainWorld('pfosDesktop', Object.freeze({ apiBase, plaid: Object.freeze({
    status:token=>ipcRenderer.invoke('pfos:plaid',{action:'status',token}),
    test:(token,values)=>ipcRenderer.invoke('pfos:plaid',{action:'test',token,values}),
    save:(token,values)=>ipcRenderer.invoke('pfos:plaid',{action:'save',token,values}),
    remove:(token,values)=>ipcRenderer.invoke('pfos:plaid',{action:'remove',token,values}),
  }), plaidLink:Object.freeze({
    status:token=>ipcRenderer.invoke('pfos:plaid-link',{action:'status',token}),
    open:(token,connectionId)=>ipcRenderer.invoke('pfos:plaid-link',{action:'open',token,connectionId}),
    check:(token,sessionId)=>ipcRenderer.invoke('pfos:plaid-link',{action:'check',token,sessionId}),
    cancel:(token,sessionId)=>ipcRenderer.invoke('pfos:plaid-link',{action:'cancel',token,sessionId}),
  }) }));
}
