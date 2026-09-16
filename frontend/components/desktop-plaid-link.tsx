'use client';
import {useEffect,useRef,useState} from 'react';

type LinkState={ok?:boolean;error?:string;status:string;session_id?:string;can_reopen?:boolean;mode?:string;target_name?:string;connections?:{id:string;name:string}[]};
type LinkBridge={status:(token:string)=>Promise<LinkState>;open:(token:string)=>Promise<LinkState>;check:(token:string,id:string)=>Promise<LinkState>;cancel:(token:string,id:string)=>Promise<LinkState>};
function bridge(){return (window as Window & {pfosDesktop?:{plaidLink?:LinkBridge}}).pfosDesktop?.plaidLink}
export function DesktopPlaidLink({configured,onConnected}:{configured:boolean;onConnected:()=>void}){
  const [state,setState]=useState<LinkState>({status:'loading'}),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const active=useRef(state),running=useRef(false),mounted=useRef(false),notify=useRef(onConnected);
  notify.current=onConnected;
  function apply(result:LinkState){
    if(!mounted.current)return;
    if(result.status==='complete' && active.current.status!=='complete')notify.current();
    active.current=result;setState(result);
  }
  async function run(action:'status'|'open'|'check'|'cancel'){
    const api=bridge();if(!api || running.current)return;
    if((action==='check'||action==='cancel')&&!active.current.session_id)return;
    running.current=true;setBusy(true);
    setError('');
    const token=localStorage.getItem('pfos_token')||'';
    try{
      const result=action==='check'||action==='cancel'?await api[action](token,active.current.session_id!):await api[action](token);
      if(!result.ok)throw new Error(result.error||'Could not check bank authorization.');
      apply(result);
    }catch(caught){
      if(mounted.current)setError(caught instanceof Error?caught.message:'Could not check bank authorization.');
      // A browser launch failure can still leave a valid saved session to resume.
      if(action==='open')try{const result=await api.status(token);if(result.ok)apply(result)}catch{}
    }finally{running.current=false;if(mounted.current)setBusy(false)}
  }
  useEffect(()=>{
    mounted.current=true;
    void run('status').then(()=>{if(mounted.current&&active.current.status==='pending')void run('check')});
    const focus=()=>{if(active.current.status==='pending')void run('check');else void run('status')};
    const timer=setInterval(()=>{if(document.visibilityState==='visible' && active.current.status==='pending' && active.current.can_reopen)void run('check')},10000);
    window.addEventListener('focus',focus);
    const changed=()=>void run('status');window.addEventListener('pfos-plaid-session-change',changed);window.addEventListener('pfos-plaid-change',changed);
    return()=>{mounted.current=false;clearInterval(timer);window.removeEventListener('focus',focus);window.removeEventListener('pfos-plaid-session-change',changed);window.removeEventListener('pfos-plaid-change',changed)};
  },[]);
  useEffect(()=>{if(configured&&mounted.current)void run('status')},[configured]);
  return <div className="card"><h2 className="font-semibold">Plaid bank connection</h2>
    <p className="mt-3 text-sm text-slate-600">Authorize your bank in your default browser, then return to PFOS. Keep PFOS open while connecting.</p>
    {!configured&&<p className="mt-3 text-sm text-slate-500">Plaid is disabled. Configure your credentials in Settings → Plaid.</p>}
    {state.status==='pending'?<>
      {state.mode==='update'&&<p className="mt-3 text-sm font-medium">Reauthorizing {state.target_name||'your bank'}. Existing accounts and transaction history will be preserved.</p>}
      <p role="status" className="mt-3 text-sm">{state.can_reopen?'Waiting for bank authorization. PFOS checks for completion automatically.':'The browser link has expired. Check for a completed connection before cancelling and starting again.'}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button disabled={busy||!configured||!state.can_reopen} onClick={()=>void run('open')} className="rounded border px-3 py-2 disabled:opacity-50">Resume in browser</button>
        <button disabled={busy||!configured} onClick={()=>void run('check')} className="rounded border px-3 py-2 disabled:opacity-50">Check connection</button>
        <button disabled={busy} onClick={()=>void run('cancel')} className="rounded border px-3 py-2 disabled:opacity-50">Cancel linking</button>
      </div><p className="mt-2 text-xs text-slate-500">Cancelling stops PFOS from saving this session. Also close the browser tab to stop authorization at your bank.</p>
    </>:<>
      {state.status==='complete'&&<p role="status" className="mt-3 text-sm">{state.connections?.map(item=>item.name).join(', ')||'Bank'} {state.mode==='update'?'reauthorized':'connected'}. Select Sync below to retrieve balances and transactions.</p>}
      {state.status==='cancelled'&&<p role="status" className="mt-3 text-sm">Bank linking ended. You can start again when ready.</p>}
      {state.status==='expired'&&<p role="status" className="mt-3 text-sm">The authorization session expired. Start a new connection.</p>}
      {state.status==='invalidated'&&<p role="status" className="mt-3 text-sm">Your Plaid credentials changed. Start a new connection with the current credentials.</p>}
      <button disabled={busy||!configured||state.status==='loading'} onClick={()=>void run('open')} className="mt-4 rounded bg-navy px-4 py-2 text-white disabled:opacity-50">{busy?'Opening…':'Connect a bank with Plaid'}</button>
    </>}
    {error&&<p role="alert" className="mt-3 text-sm text-red-700">{error} <button className="underline" disabled={busy} onClick={()=>void run(state.status==='pending'?'check':'status')}>Retry</button></p>}
  </div>;
}
