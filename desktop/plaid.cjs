'use strict';
const fs=require('node:fs/promises');
const path=require('node:path');
const {randomUUID}=require('node:crypto');
const {isAppNavigation}=require('./policy.cjs');
const {isHostedLink}=require('./plaid-link.cjs');
function validate(values) {
  if(!values || !['sandbox','production'].includes(values.environment) ||
    ['client_id','secret'].some(key=>typeof values[key]!=='string' || !values[key].trim() || values[key].length>256))
    throw new Error('Enter your Plaid Client ID, secret, and Sandbox or Production environment.');
  return {client_id:values.client_id.trim(),secret:values.secret.trim(),environment:values.environment};
}
function createPlaidVault(profile,secure,platform=process.platform) {
  const file=path.join(profile,'plaid-credentials.json');
  async function available(){return platform==='darwin' && await secure.isAsyncEncryptionAvailable()}
  async function load() {
    let raw;
    try{raw=await fs.readFile(file,'utf8')}catch(error){if(error.code==='ENOENT')return null;throw new Error('Could not read saved Plaid settings.')}
    try {
      if(!await available())throw new Error();
      const stored=JSON.parse(raw);
      if(stored.version!==1)throw new Error();
      const decrypted=await secure.decryptStringAsync(Buffer.from(stored.encrypted,'base64'));
      const values=validate(JSON.parse(decrypted.result));
      if(values.client_id!==stored.client_id || values.environment!==stored.environment)throw new Error();
      return values;
    }catch{throw new Error('Saved Plaid credentials could not be unlocked with macOS Keychain. Plaid is disabled.')}
  }
  async function save(input) {
    const values=validate(input);
    if(!await available())throw new Error('macOS Keychain is unavailable. Credentials were not saved.');
    let encrypted;
    try{encrypted=(await secure.encryptStringAsync(JSON.stringify(values))).toString('base64')}
    catch{throw new Error('macOS Keychain could not protect the Plaid secret. Credentials were not saved.')}
    const temporary=file+'.'+randomUUID()+'.tmp';
    try {
      const handle=await fs.open(temporary,'wx',0o600);
      try{await handle.writeFile(JSON.stringify({version:1,client_id:values.client_id,environment:values.environment,encrypted}));await handle.sync()}finally{await handle.close()}
      await fs.rename(temporary,file);
    }catch{throw new Error('Could not save protected Plaid settings.')}finally{await fs.rm(temporary,{force:true})}
  }
  async function remove() {
    try{await fs.rm(file,{force:true})}catch{throw new Error('Could not remove saved Plaid credentials. They have not been removed.')}
  }
  return {load,save,remove,available};
}
async function testPlaidCredentials(input,fetcher=fetch) {
  const values=validate(input);
  let response;
  try{response=await fetcher('https://'+values.environment+'.plaid.com/link/token/create',{
    method:'POST',headers:{'Content-Type':'application/json'},redirect:'error',signal:AbortSignal.timeout(30000),
    body:JSON.stringify({client_id:values.client_id,secret:values.secret,client_name:'PFOS',language:'en',country_codes:['US'],
      products:['transactions'],hosted_link:{completion_redirect_uri:'pfos://plaid-complete',is_mobile_app:false,url_lifetime_seconds:1800},user:{client_user_id:'pfos-test-'+randomUUID()}})})}
  catch{throw new Error('Could not reach Plaid. Check your internet connection and try again.')}
  const body=await response.json().catch(()=>({}));
  if(!response.ok){
    const errors={INVALID_API_KEYS:'Plaid rejected the Client ID or secret for this environment.',
      INVALID_PRODUCT:'Transactions is not available for this Plaid account.',UNAUTHORIZED_ENVIRONMENT:'This Plaid account cannot use the selected environment.',
      INVALID_FIELD:'Review Hosted Link settings and add pfos://plaid-complete to allowed completion redirect URIs in your Plaid dashboard.',
      INVALID_LINK_CUSTOMIZATION:'Configure Plaid Link and its data-use settings in your Plaid dashboard.',
      UNAUTHORIZED_ROUTE_ACCESS:'Your Plaid account does not have access to this operation.'};
    throw new Error(errors[body.error_code] || 'Plaid could not validate Transactions access. Review product access and Hosted Link configuration in your Plaid dashboard, including the allowed completion redirect URI pfos://plaid-complete.');
  }
  if(typeof body.link_token!=='string' || !isHostedLink(body.hosted_link_url))throw new Error('Plaid returned an unexpected validation response.');
  return {message:'Credentials accepted. Plaid can create a Hosted Link for Transactions. Connect a bank from Connected Sources.'};
}
function registerPlaidIPC({ipcMain,vault,getBackend,getWindow,origin,canConfigure=()=>true}) {
  let busy=false;
  ipcMain.handle('pfos:plaid',async(event,{action,token,values}={})=>{
    try {
      const window=getWindow();
      if(!window || window.isDestroyed() || event.sender!==window.webContents || event.senderFrame!==window.webContents.mainFrame || !isAppNavigation(event.senderFrame.url,origin))
        throw new Error('Open Plaid settings from the PFOS window.');
      const runtime=getBackend();
      const auth=await fetch(runtime.url+'/api/v1/auth/me',{headers:{Authorization:'Bearer '+token,'X-PFOS-Desktop-Token':runtime.token},signal:AbortSignal.timeout(5000)});
      if(!auth.ok || (await auth.json()).role!=='ADMIN')throw new Error('Sign in as a household administrator to configure Plaid.');
      if(action==='status'){
        try{
          const saved=await vault.load();
          return {ok:true,configured:Boolean(saved),stored:Boolean(saved),client_id:saved?.client_id||'',environment:saved?.environment||'sandbox'};
        }catch{return {ok:true,configured:false,stored:true,client_id:'',environment:'sandbox',error:'Saved credentials cannot be unlocked. Replace them or remove them from this computer.'}}

      }
      if(!['test','save','remove'].includes(action))throw new Error('Unknown Plaid settings action.');
      if(busy)throw new Error('A Plaid configuration operation is already running.');
      if(!canConfigure())throw new Error('Finish backup or restore before changing Plaid settings.');
      busy=true;
      try{
        if(action==='remove'){
          if(values?.confirmed!==true)throw new Error('Confirm removal of this computer’s Plaid credentials first.');
          await vault.remove();
          try{await runtime.updatePlaid(null)}catch{
            await runtime.stop();
            throw new Error('Saved Plaid credentials were removed. Restart PFOS to finish disabling Plaid.');
          }
          return {ok:true,configured:false,stored:false,message:'Plaid credentials removed from this computer. Imported accounts and transactions are preserved. This does not revoke consent at your bank or delete its saved bank tokens.'};
        }
        const previous=await vault.load().catch(error=>{if(values?.secret?.trim())return null;throw error});
        const candidate=validate({...values,secret:values?.secret || (previous?.client_id===values?.client_id && previous?.environment===values?.environment?previous.secret:'')});
        if(action==='save' && previous && ['client_id','secret','environment'].some(key=>candidate[key]!==previous[key]) && values?.confirmed!==true)
          throw new Error('Review and confirm replacement of this computer’s Plaid credentials first.');
        const result=await testPlaidCredentials(candidate);
        if(action==='save'){
          if(!canConfigure())throw new Error('PFOS is closing or performing maintenance. Credentials were not changed.');
          await vault.save(candidate);
          try{await runtime.updatePlaid(candidate)}catch{
            // Never continue using a previous credential after a saved replacement.
            await runtime.stop();
            throw new Error('Credentials saved, but PFOS must be restarted to apply them.');
          }
        }
        return {ok:true,...result,configured:action==='save'?true:Boolean(previous)};
      }finally{busy=false}
    }catch(error){return {ok:false,error:error.message || 'Unable to configure Plaid.'}}
  });
  return ()=>busy;
}
module.exports={createPlaidVault,testPlaidCredentials,registerPlaidIPC};
