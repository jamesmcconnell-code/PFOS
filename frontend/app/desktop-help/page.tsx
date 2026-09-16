'use client';
import Link from 'next/link';
import {useEffect,useState} from 'react';
import {api} from '@/lib/api';

type Connection={id:string;provider:string;name:string;plaid_state?:string};
export default function DesktopHelp(){
  const [restored,setRestored]=useState(false),[signedIn,setSignedIn]=useState(false),[configured,setConfigured]=useState<boolean|null>(null),[banks,setBanks]=useState<Connection[]>([]),[error,setError]=useState('');
  useEffect(()=>{
    setRestored(new URLSearchParams(window.location.search).get('restored')==='1');
    let live=true;
    const refresh=async()=>{
      const signed=Boolean(localStorage.getItem('pfos_token'));if(live)setSignedIn(signed);
      if(!signed)return;
      try{
        const [config,rows]=await Promise.all([api('/connections/plaid/configuration'),api('/connections')]);
        if(live){setConfigured(config.configured);setBanks(rows.filter((row:Connection)=>row.provider==='plaid'));setError('')}
      }catch{if(live)setError('Sign in to check restored bank connections. Your local data can still be reviewed after signing in.')}
    };
    void refresh();window.addEventListener('focus',refresh);window.addEventListener('pfos-plaid-change',refresh);
    return()=>{live=false;window.removeEventListener('focus',refresh);window.removeEventListener('pfos-plaid-change',refresh)};
  },[]);
  const needsNew=banks.filter(bank=>['different_credentials','new_connection_required'].includes(bank.plaid_state||''));
  const needsLogin=banks.filter(bank=>bank.plaid_state==='reauthorization_required');
  return <div className="max-w-4xl space-y-6">
    <h1 className="text-3xl font-bold">Backups and moving to another Mac</h1>
    {restored&&<div role="status" className="rounded-xl border border-emerald-300 bg-emerald-50 p-4"><h2 className="font-semibold">Backup restored — next steps</h2><p className="mt-2">Sign in with an account and password from the backup. Review your restored accounts before syncing. This Mac’s Plaid developer credentials were not replaced.</p></div>}
    <section className="card"><h2 className="text-xl font-semibold">What a backup contains</h2>
      <p className="mt-3">A PFOS backup contains your financial database, local users and password hashes, saved preferences in the database, bank and exchange connection tokens, and the local keys needed to read that data.</p>
      <p className="mt-3 font-medium">The backup file is not encrypted. Even encrypted connection tokens can be read using the keys inside the backup. Treat it as private financial data and keep it in a protected location.</p>
      <p className="mt-3">It does not include your installation’s Plaid Client ID/secret settings, macOS Keychain protection, browser sign-in session, or device-only preferences such as Blur financial numbers. A DMG contains the application, not your financial data.</p>
    </section>
    <section className="card"><h2 className="text-xl font-semibold">Create a backup</h2>
      <ol className="mt-3 list-decimal space-y-2 pl-6"><li>Finish or cancel pending bank authorization and wait for syncing or credential changes to finish.</li><li>Choose <b>File → Back Up Local Data…</b> in the macOS menu bar.</li><li>Save a new <code>.pfosbackup</code> file in a protected location. Keep a separate copy away from this Mac so a device failure does not destroy both copies.</li></ol>
      <p className="mt-3">Use the app’s backup command to capture a consistent database. Copying the app or a database file while PFOS is running is not a substitute.</p>
    </section>
    <section className="card"><h2 className="text-xl font-semibold">Restore or move to a new Mac</h2>
      <ol className="mt-3 list-decimal space-y-2 pl-6"><li>Install a compatible PFOS version on the destination Mac and transfer your backup privately. Do not send your backup to someone who only needs the installer.</li><li>Open PFOS and choose <b>File → Restore Local Backup…</b>. You can do this before creating a household. If PFOS cannot start, its startup error dialog also offers restore.</li><li>Review the confirmation. Restore replaces the destination’s local data; it does not merge households. PFOS first preserves the current data in a recovery copy.</li><li>Sign in using credentials from the backup. Review account balances, transaction history, and preferences. Enable <b>Settings → Visual preferences → Blur financial numbers</b> again if wanted.</li><li>Follow the Plaid setup guidance below before syncing. Keep the original Mac and backup until you have checked the restored data.</li></ol>
      <p className="mt-3">For your own household, this app reads data locally. Changes made separately on two Macs do not synchronize or merge automatically.</p>
    </section>
    <section className="card"><h2 className="text-xl font-semibold">Check Plaid after restoring</h2>
      <p className="mt-3">Restore keeps any Plaid developer credentials already saved on the destination Mac. A new Mac needs its own setup in <b>Settings → Plaid</b>; do not copy the old Mac’s protected credential file.</p>
      <ul className="mt-3 list-disc space-y-2 pl-6"><li><b>Same Plaid Client ID and environment:</b> enter that account’s current secret and validate it. Restored bank tokens can be used if the bank still accepts them.</li><li><b>Bank authorization required:</b> choose <b>Connected Sources → Manage → Reauthorize bank</b> to renew access while retaining existing history.</li><li><b>Different or unknown Plaid credentials:</b> restore the original credentials or connect the bank as a separate source. Review possible overlapping accounts and transactions before syncing; PFOS does not automatically merge them.</li><li><b>No Plaid account:</b> keep using restored data, manual entries, and CSV imports. Plaid stays disabled.</li></ul>
      <p className="mt-3">Pending links saved in an older backup may be expired or belong to another setup. Cancel them and start again if needed. A restored token is not proof that a live bank connection is healthy.</p>
      {!signedIn?<p className="mt-4"><Link className="font-medium underline" href="/login">Sign in to review restored connections</Link></p>:<div className="mt-4 rounded border p-3" role="status">
        {error?<p>{error} <Link className="underline" href="/login">Sign in</Link></p>:<>
          <p>{configured===null?'Checking local Plaid setup…':configured?'Plaid credentials are configured on this Mac.':'Plaid is disabled on this Mac. Add your own credentials in Settings → Plaid to enable bank syncing.'}</p>
          {needsNew.length>0&&<p className="mt-2">Review credentials or connect separately: {needsNew.map(bank=>bank.name).join(', ')}.</p>}
          {needsLogin.length>0&&<p className="mt-2">Bank authorization required: {needsLogin.map(bank=>bank.name).join(', ')}.</p>}
          {configured!==null&&banks.length===0&&<p className="mt-2">No saved Plaid bank connections were found.</p>}
          <Link className="mt-3 inline-block font-medium underline" href="/connections">Review Connected Sources</Link>
        </>}
      </div>}
    </section>
    <section className="card"><h2 className="text-xl font-semibold">Recovery and application updates</h2>
      <p className="mt-3">Choose <b>File → Show Data Folder…</b> to find recovery copies in its <code>backups</code> folder. A normal pre-restore copy is a <code>.pfosbackup</code> file; damaged originals may instead be preserved in a folder for manual recovery. Keep those originals.</p>
      <p className="mt-3">PFOS validates a backup before replacing data. If an archive is rejected, keep the originals and try a known-good backup or a compatible newer app version.</p>
      <p className="mt-3">To update the app on the same Mac, quit PFOS and replace the application using the new DMG. You normally do not need to restore a backup. Your local profile and protected Plaid settings remain on that Mac.</p>
    </section>
  </div>;
}
