'use client';
import {useEffect,useState} from 'react';
import Link from 'next/link';

type Values={client_id:string;secret:string;environment:string;confirmed?:boolean};
type Result={ok:boolean;error?:string;message?:string;configured?:boolean;stored?:boolean;client_id?:string;environment?:string};
type Bridge={status:(token:string)=>Promise<Result>;test:(token:string,values:Values)=>Promise<Result>;save:(token:string,values:Values)=>Promise<Result>;remove:(token:string,values:{confirmed:boolean})=>Promise<Result>};
function bridge(){return (window as Window & {pfosDesktop?:{plaid?:Bridge}}).pfosDesktop?.plaid}
export function PlaidSettings(){
  const [clientId,setClientId]=useState(''),[secret,setSecret]=useState(''),[environment,setEnvironment]=useState('sandbox');
  const [stored,setStored]=useState(false),[saved,setSaved]=useState({client_id:'',environment:'sandbox'}),[review,setReview]=useState<'save'|'remove'|null>(null);
  const [configured,setConfigured]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[supported,setSupported]=useState(false),[loading,setLoading]=useState(true);
  useEffect(()=>{
    const api=bridge();setSupported(Boolean(api));
    if(api)void api.status(localStorage.getItem('pfos_token')||'').then(result=>{
      if(!result.ok){setMessage(result.error||'Could not read local Plaid settings');return}
      setClientId(result.client_id||'');setEnvironment(result.environment||'sandbox');setConfigured(Boolean(result.configured));setStored(Boolean(result.stored??result.configured));setSaved({client_id:result.client_id||'',environment:result.environment||'sandbox'});if(result.error)setMessage(result.error);
    }).catch(()=>setMessage('Could not read local Plaid settings')).finally(()=>setLoading(false));
  },[]);
  async function run(action:'test'|'save'|'remove',confirmed=false){
    const api=bridge();if(!api)return;setBusy(true);setMessage('');
    try{
      const token=localStorage.getItem('pfos_token')||'';
      const result=action==='remove'?await api.remove(token,{confirmed}):await api[action](token,{client_id:clientId,secret,environment,confirmed});
      if(!result.ok)throw new Error(result.error);
      setMessage(action==='save'?'Saved on this computer. '+result.message:result.message||'Test succeeded.');
      if(action==='save'){setConfigured(true);setStored(true);setSaved({client_id:clientId.trim(),environment});setSecret('');window.dispatchEvent(new Event('pfos-plaid-change'));}
      if(action==='remove'){setConfigured(false);setStored(false);setSecret('');setClientId('');setEnvironment('sandbox');setSaved({client_id:'',environment:'sandbox'});window.dispatchEvent(new Event('pfos-plaid-change'));}
    }catch(error){setMessage(error instanceof Error?error.message:'Could not configure Plaid')}
    finally{setBusy(false);setReview(null)}
  }
  const identityChanged=clientId.trim()!==saved.client_id||environment!==saved.environment;
  function save(){if(stored&&(identityChanged||secret.trim()||!configured))setReview('save');else void run('save')}
  return <section><p className="mb-3 text-sm"><Link href="/desktop-help" onClick={()=>window.dispatchEvent(new Event('pfos-close-settings'))} className="underline">Backup and migration guide</Link></p><h3 className="font-semibold">Your Plaid account</h3><p className="mt-2 text-sm text-slate-600">Use your own Plaid developer credentials on this computer. PFOS never supplies a shared developer key.</p>
    {!supported?<p className="mt-4 text-sm">Per-installation Plaid settings are available in the macOS desktop app.</p>:<>
      <p className="mt-3 text-sm font-medium">{configured?'Credentials saved locally':stored?'Saved credentials unavailable':'Plaid is not configured'}</p>
      <p className="mt-2 text-xs text-slate-500">The secret is protected with macOS Keychain and is not included in household backups. Bank authorization opens in your default browser.</p>
      <form className="mt-4 space-y-4" onSubmit={event=>{event.preventDefault();save()}}><fieldset disabled={busy||loading||review!==null} className="space-y-4">
        <label className="block text-sm font-medium">Client ID<input aria-label="Plaid Client ID" autoComplete="off" spellCheck={false} maxLength={256} className="mt-1 w-full rounded border p-2" value={clientId} onChange={event=>setClientId(event.target.value)} required/></label>
        <label className="block text-sm font-medium">Secret<input aria-label="Plaid secret" type="password" autoComplete="new-password" maxLength={256} className="mt-1 w-full rounded border p-2" value={secret} onChange={event=>setSecret(event.target.value)} placeholder={configured?'Leave blank to keep the saved secret':'Enter your Plaid secret'}/></label>
        <label className="block text-sm font-medium">Environment<select aria-label="Plaid environment" className="mt-1 w-full rounded border p-2" value={environment} onChange={event=>setEnvironment(event.target.value)}><option value="sandbox">Sandbox — test data</option><option value="production">Production — real bank access</option></select></label>
        <p className="text-xs text-slate-500">In your Plaid dashboard, add pfos://plaid-complete to the allowed Hosted Link completion redirect URIs. Testing contacts Plaid and checks Hosted Link access for Transactions. It does not link a bank or save changes. Saving also validates first. Production requires appropriate access from Plaid.</p>
        <div className="flex gap-2"><button type="button" onClick={()=>void run('test')} className="rounded border px-3 py-2 text-sm">Test connection</button><button className="rounded bg-navy px-3 py-2 text-sm text-white">{busy?'Working…':stored&&(identityChanged||secret.trim())?'Review replacement':'Validate and save'}</button></div>
      </fieldset></form>
      {stored&&!review&&<button type="button" disabled={busy||loading} onClick={()=>setReview('remove')} className="mt-5 rounded border border-red-300 px-3 py-2 text-sm text-red-700">Remove Plaid credentials</button>}
      {review&&<div role="alertdialog" aria-label={review==='remove'?'Remove Plaid credentials':'Replace Plaid credentials'} className="mt-5 rounded border border-amber-300 bg-amber-50 p-4 text-sm">
        <p className="font-semibold">{review==='remove'?'Remove credentials from this computer?':'Replace this computer’s Plaid credentials?'}</p>
        <p className="mt-2">{review==='remove'?'Plaid linking and syncing will be disabled for everyone using this installation. Imported accounts, transactions, and saved bank tokens will remain. This does not revoke bank consent.':'New credentials are validated before replacing the saved settings. Imported accounts and transactions will remain.'}</p>
        {review==='save'&&<p className="mt-2">{identityChanged?'Banks linked under the previous Client ID or environment cannot sync with the new credentials. Restore their original credentials or connect those banks separately; review overlapping accounts and transactions before syncing.':'Rotating the secret for the same Client ID and environment keeps existing bank tokens usable. Banks that request authorization can be reauthorized in Connected Sources.'}</p>}
        <p className="mt-2">Pending bank authorization sessions will be cancelled. Close any bank-linking browser tabs.</p>
        <div className="mt-3 flex gap-2"><button type="button" disabled={busy} onClick={()=>setReview(null)} className="rounded border px-3 py-2">Keep current settings</button><button type="button" disabled={busy} onClick={()=>void run(review,true)} className="rounded bg-navy px-3 py-2 text-white">{busy?'Working…':review==='remove'?'Confirm removal':'Validate and replace'}</button></div>
      </div>}

    </>}{message&&<p role="status" className="mt-4 rounded bg-slate-100 p-3 text-sm">{message}</p>}
  </section>;
}
