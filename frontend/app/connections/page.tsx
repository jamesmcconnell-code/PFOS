'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { DesktopPlaidLink } from '@/components/desktop-plaid-link';
import { Protected } from '@/components/protected';

const providers = ['coinbase', 'gemini'] as const;
type Connection = Record<string, any>;

declare global {
  interface Window {
    Plaid?: { create: (config: { token: string; onSuccess: (token: string, metadata: { institution?: { name?: string } }) => void; onExit: () => void }) => { open: () => void } };
  }
}

export default function ConnectedSources() {
  const [desktop,setDesktop]=useState(false);
  const [plaidConfigured,setPlaidConfigured]=useState(false);
  const [rows, setRows] = useState<Connection[]>([]);
  const [provider, setProvider] = useState<'coinbase' | 'gemini'>('coinbase');
  const [name, setName] = useState('');
  const [key, setKey] = useState('');
  const [secret, setSecret] = useState('');
  const [message, setMessage] = useState('');
  const [selected, setSelected] = useState<Connection | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const load = () => api('/connections').then(result=>{setRows(result);setSelected(current=>current?result.find((row:Connection)=>row.id===current.id)||null:null)});
  useEffect(() => { setDesktop(Boolean((window as Window & {pfosDesktop?:unknown}).pfosDesktop));const refresh=()=>{void load().catch(()=>{});return api('/connections/plaid/configuration').then(result=>setPlaidConfigured(result.configured)).catch(()=>setPlaidConfigured(false))};void refresh();window.addEventListener('focus',refresh);window.addEventListener('pfos-plaid-change',refresh);return()=>{window.removeEventListener('focus',refresh);window.removeEventListener('pfos-plaid-change',refresh)}; }, []);

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api('/connections', { method: 'POST', body: JSON.stringify({ provider, name: name || provider, credentials: { api_key: key, api_secret: secret } }) });
      setMessage('Connection saved. Select Sync to retrieve current balances.');
      setKey(''); setSecret(''); await load();
    } catch (caught) { setMessage(caught instanceof Error ? caught.message : 'Unable to save connection'); }
  }

  async function sync(connection: Connection) {
    setSyncing(connection.id);
    try {
      const result = await api(`/connections/${connection.id}/sync`, { method: 'POST' });
      setMessage(`Sync complete: ${result.imported} transactions imported, ${result.duplicates} duplicates skipped.`);
      await load();
    } catch (caught) { setMessage(caught instanceof Error ? caught.message : 'Sync failed'); }
    finally { setSyncing(null);await load(); }
  }

  async function unlink() {
    if (!selected) return;
    try {
      await api(`/connections/${selected.id}`, { method: 'DELETE' });
      setSelected(null); setConfirmingDelete(false);
      setMessage('Source unlinked. Its encrypted token, imported accounts, transactions, and sync history were removed.');
      await load();
    } catch (caught) { setMessage(caught instanceof Error ? caught.message : 'Could not unlink source'); }
  }

  async function reconnect(connection:Connection){
    const link=(window as Window & {pfosDesktop?:{plaidLink?:{open:(token:string,id?:string)=>Promise<{ok:boolean;error?:string}>}}}).pfosDesktop?.plaidLink;
    if(!link)return;
    setSyncing(connection.id);
    try{
      const result=await link.open(localStorage.getItem('pfos_token')||'',connection.reconnect_mode==='update'?connection.id:undefined);
      if(!result.ok)throw new Error(result.error);
      setSelected(null);setMessage('Continue bank authorization in your browser.');
    }catch(error){setMessage(error instanceof Error?error.message:'Could not reconnect bank')}
    finally{setSyncing(null);window.dispatchEvent(new Event('pfos-plaid-session-change'));await load()}
  }

  async function launchPlaid() {
    try {
      const { link_token } = await api('/connections/plaid/link-token', { method: 'POST' });
      if (!window.Plaid) await new Promise<void>((resolve, reject) => {
        const script = document.createElement('script'); script.src = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js';
        script.onload = () => resolve(); script.onerror = () => reject(new Error('Could not load Plaid Link')); document.head.appendChild(script);
      });
      window.Plaid!.create({ token: link_token, onSuccess: async (public_token, metadata) => {
        try {
          const connection = await api('/connections/plaid/exchange', { method: 'POST', body: JSON.stringify({ public_token, name: metadata.institution?.name || 'Plaid bank' }) });
          setMessage(`${connection.name} connected. Select Sync to retrieve its balances and transactions.`);
          await load();
        } catch (caught) { setMessage(caught instanceof Error ? caught.message : 'Could not save Plaid connection'); }
      }, onExit: () => {} }).open();
    } catch(error) { setMessage(error instanceof Error?error.message:'Plaid Link could not start'); }
  }

  return <Protected>
    <h1 className="text-3xl font-bold">Connected Sources</h1>
    <p className="mt-1 text-slate-500">Manage bank and exchange connections. You can sync whenever you need current balances and activity.</p>
    {message && <p className="mt-5 rounded-xl bg-slate-100 p-3 text-sm" role="status">{message}</p>}
    <section className="mt-6 grid gap-5 lg:grid-cols-2">
      <form onSubmit={connect} className="card"><h2 className="font-semibold">Add exchange connection</h2>
        <select className="mt-4 w-full rounded border p-2" value={provider} onChange={(event) => setProvider(event.target.value as typeof provider)}>{providers.map((item) => <option key={item}>{item}</option>)}</select>
        <input className="mt-3 w-full rounded border p-2" value={name} onChange={(event) => setName(event.target.value)} placeholder="Use existing source name to replace keys" />
        <input className="mt-3 w-full rounded border p-2" value={key} onChange={(event) => setKey(event.target.value)} placeholder="API key" required />
        <textarea className="mt-3 min-h-24 w-full rounded border p-2" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder="API secret / private key" required />
        <button className="mt-4 rounded bg-navy px-4 py-2 text-white">Save connection</button>
      </form>
      {desktop?<DesktopPlaidLink configured={plaidConfigured} onConnected={()=>void load()}/>:<div className="card"><h2 className="font-semibold">Plaid bank connection</h2>{!plaidConfigured&&<p className="mt-3 text-sm text-slate-500">Plaid is disabled. Configure your credentials in Settings → Plaid.</p>}<button disabled={!plaidConfigured} onClick={launchPlaid} className="mt-4 rounded bg-navy px-4 py-2 text-white">Connect a bank with Plaid</button></div>}
    </section>
    <section className="mt-6"><h2 className="font-semibold">Connected sources</h2>
      <div className="mt-3 space-y-3">{rows.map((connection) => <div className="card flex items-center justify-between gap-4" key={connection.id}>
        <button onClick={() => { setSelected(connection); setConfirmingDelete(false); }} className="min-w-0 text-left"><b className="capitalize">{connection.provider}</b><p className="truncate text-sm text-slate-500">{connection.name} · {connection.last_synced_at ? `Synced ${connection.last_synced_at}` : 'Not synced yet'}</p>{connection.plaid_state&&connection.plaid_state!=='ready'&&<p className="mt-1 text-sm text-amber-700">{connection.plaid_state==='credentials_missing'?'Plaid credentials missing':connection.plaid_state==='reauthorization_required'?'Bank authorization required':'Different credentials or new bank connection required'}</p>}</button>
        <div className="flex shrink-0 gap-2">{connection.provider !== 'csv' && <button onClick={() => void sync(connection)} disabled={syncing === connection.id || (connection.provider==='plaid'&&(!plaidConfigured||connection.can_sync===false))} className="rounded border px-3 py-2 text-sm disabled:opacity-60">{syncing === connection.id ? 'Syncing…' : 'Sync'}</button>}<button onClick={() => { setSelected(connection); setConfirmingDelete(false); }} className="rounded border px-3 py-2 text-sm">Manage</button></div>
      </div>)}</div>
    </section>
    {selected && <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4" role="dialog" aria-modal="true" aria-labelledby="source-manager">
      <div className="w-full max-w-md rounded-2xl bg-white p-6"><div className="flex items-start justify-between gap-4"><div><p className="label capitalize">{selected.provider}</p><h2 id="source-manager" className="mt-1 text-xl font-bold">{selected.name}</h2></div><button onClick={() => setSelected(null)} aria-label="Close source manager">×</button></div>
        {desktop&&selected.provider==='plaid'&&!confirmingDelete&&<div className="mt-4 rounded border p-3 text-sm"><p>{selected.plaid_message}</p>{selected.reconnect_mode&&<button disabled={!plaidConfigured||syncing===selected.id} onClick={()=>void reconnect(selected)} className="mt-3 rounded bg-navy px-3 py-2 text-white disabled:opacity-50">{syncing===selected.id?'Opening…':selected.reconnect_mode==='update'?'Reauthorize bank':'Connect as separate source'}</button>}</div>}
        {!confirmingDelete ? <><p className="mt-3 text-sm text-slate-600">Sync this source on demand or unlink it from PFOS.</p><div className="mt-6 flex flex-wrap justify-between gap-3"><button onClick={() => setConfirmingDelete(true)} className="text-sm text-red-700">Unlink source</button><div className="flex gap-2"><button onClick={() => setSelected(null)} className="rounded border px-3 py-2">Close</button>{selected.provider !== 'csv' && <button onClick={() => void sync(selected)} disabled={syncing === selected.id || (selected.provider==='plaid'&&(!plaidConfigured||selected.can_sync===false))} className="rounded bg-navy px-3 py-2 text-white disabled:opacity-60">{syncing === selected.id ? 'Syncing…' : 'Sync now'}</button>}</div></div></> : <><p className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">This permanently removes the connection’s encrypted provider token, imported accounts, imported transactions, and sync history. Your PFOS users, household, manual accounts, goals, and settings are preserved.</p><div className="mt-6 flex justify-end gap-2"><button onClick={() => setConfirmingDelete(false)} className="rounded border px-3 py-2">Cancel</button><button onClick={() => void unlink()} className="rounded bg-red-700 px-3 py-2 text-white">Unlink and delete data</button></div></>}
      </div>
    </div>}
  </Protected>;
}
