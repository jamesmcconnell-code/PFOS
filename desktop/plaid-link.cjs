'use strict';
const {isAppNavigation}=require('./policy.cjs');
const COMPLETION_URI='pfos://plaid-complete';
function isPlaidCompletion(value) {
  // This is only a wake-up signal, never proof of authorization. No callback
  // tokens, paths, or query parameters are accepted from another application.
  return value===COMPLETION_URI || value===COMPLETION_URI+'/';
}
function isHostedLink(value) {
  try {
    const url=new URL(value);
    return url.protocol==='https:' && url.hostname==='secure.plaid.com' && !url.port &&
      !url.username && !url.password && url.pathname.startsWith('/hl/') && !url.hash;
  } catch { return false; }
}
function registerPlaidLinkIPC({ipcMain,getBackend,getWindow,origin,openExternal}) {
  let opening=false;
  ipcMain.handle('pfos:plaid-link',async(event,{action,token,sessionId,connectionId}={})=>{
    try {
      const window=getWindow();
      if(!window || window.isDestroyed() || event.sender!==window.webContents ||
         event.senderFrame!==window.webContents.mainFrame || !isAppNavigation(event.senderFrame.url,origin))
        throw new Error('Open bank connections from the PFOS window.');
      const runtime=getBackend();
      const headers={'Content-Type':'application/json',Authorization:'Bearer '+token,'X-PFOS-Desktop-Token':runtime.token};
      const base=runtime.url+'/api/v1/connections/plaid/hosted';
      let url=base,method='GET';
      if(action==='open'){
        url+='/start';method='POST';
        if(connectionId!==undefined){
          if(typeof connectionId!=='string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(connectionId))throw new Error('Invalid bank connection.');
          url+='?connection_id='+connectionId;
        }
      }
      else if(['check','cancel'].includes(action)){
        if(typeof sessionId!=='string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sessionId))
          throw new Error('Invalid bank authorization session.');
        url+='/'+sessionId+(action==='check'?'/poll':'/cancel');method='POST';
      }else if(action!=='status')throw new Error('Unknown bank authorization action.');
      if(action==='open' && opening)throw new Error('Bank authorization is already opening.');
      if(action==='open')opening=true;
      try {
        const response=await fetch(url,{method,headers,signal:AbortSignal.timeout(120000)});
        const result=await response.json();
        if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Bank authorization request failed.');
        if(action==='open'){
          if(!result.can_reopen)throw new Error('This browser link has expired. Check for a completed connection, or cancel and start again.');
          if(!isHostedLink(result.hosted_link_url))throw new Error('Plaid returned an unexpected browser address.');
          try{await openExternal(result.hosted_link_url)}catch{throw new Error('Could not open your browser. Try Resume in browser.');}
        }
        // The browser URL is a short-lived capability; keep it out of the UI.
        return {ok:true,status:result.status,session_id:result.session_id,
          can_reopen:result.can_reopen,connections:result.connections||[],mode:result.mode,target_id:result.target_id,target_name:result.target_name};
      }finally{if(action==='open')opening=false}
    }catch(error){return {ok:false,error:error.message||'Could not complete bank authorization.'}}
  });
}
module.exports={COMPLETION_URI,isPlaidCompletion,isHostedLink,registerPlaidLinkIPC};
