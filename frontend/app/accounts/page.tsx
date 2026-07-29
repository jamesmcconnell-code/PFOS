'use client';

import { useEffect, useState } from 'react';
import { api, money } from '@/lib/api';
import { Protected } from '@/components/protected';

const roles = ['spending', 'income', 'debt', 'brokerage', 'crypto'];
type Account = Record<string, any>;

export default function Accounts() {
  const [rows, setRows] = useState<Account[]>([]);
  const [members, setMembers] = useState<Account[]>([]);
  const [selected, setSelected] = useState<Account | null>(null);
  const [balance, setBalance] = useState('');
  const [newName, setNewName] = useState('');
  const [newRole, setNewRole] = useState('spending');
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState('');

  const load = () => api('/accounts').then(setRows);
  useEffect(() => {
    void load();
    api('/household/members').then(setMembers).catch(() => setMembers([]));
  }, []);

  function open(account: Account) {
    setSelected({ ...account });
    setBalance(String(account.balance));
    setDeleting(false);
    setError('');
  }

  async function add(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api('/accounts', {
        method: 'POST',
        body: JSON.stringify({ name: newName, type: 'manual', balance: 0, account_type: newRole }),
      });
      setNewName('');
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not add account');
    }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    try {
      await api(`/accounts/${selected.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: selected.name,
          balance: Number(balance),
          account_type: selected.account_type,
          ownership: selected.ownership,
          owner_id: selected.ownership === 'individual' ? selected.owner_id : null,
        }),
      });
      setSelected(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not update account');
    }
  }

  async function remove() {
    if (!selected) return;
    try {
      await api(`/accounts/${selected.id}`, { method: 'DELETE' });
      setSelected(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not delete account');
    }
  }

  return <Protected>
    <h1 className="text-3xl font-bold">Accounts</h1>
    <p className="mt-1 text-slate-500">Classify each account for accurate household reporting.</p>
    {error && !selected && <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <div className="mt-6 grid gap-4 md:grid-cols-3">
      {rows.map((account) => <button key={account.id} onClick={() => open(account)} className="card text-left transition hover:-translate-y-0.5 hover:ring-2 hover:ring-mint">
        <div className="flex justify-between gap-2"><span className="label capitalize">{account.account_type}</span><span className="text-xs text-slate-400">{account.ownership === 'joint' ? 'Joint' : account.owner_name}</span></div>
        <b className="mt-2 block">{account.name}</b>
        <p className="metric mt-3">{money(account.balance)}</p>
        <p className="mt-2 text-xs text-slate-400">{account.source_name} · Click to edit</p>
      </button>)}
    </div>
    <form onSubmit={add} className="card mt-6 flex flex-wrap items-center gap-3">
      <input className="rounded border p-2" placeholder="Account name" value={newName} onChange={(event) => setNewName(event.target.value)} required />
      <select className="rounded border p-2" value={newRole} onChange={(event) => setNewRole(event.target.value)}>{roles.map((role) => <option key={role}>{role}</option>)}</select>
      <button className="rounded bg-navy px-4 py-2 text-white">Add manual account</button>
    </form>
    {selected && <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4" role="dialog" aria-modal="true" aria-labelledby="account-editor">
      <form onSubmit={save} className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
        <div className="flex justify-between"><h2 id="account-editor" className="text-xl font-bold">Edit account</h2><button type="button" onClick={() => setSelected(null)} aria-label="Close editor">×</button></div>
        {error && <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        <label className="label mt-4 block">Name</label>
        <input className="mt-1 w-full rounded border p-2" value={selected.name} onChange={(event) => setSelected({ ...selected, name: event.target.value })} required />
        <label className="label mt-4 block">Financial role</label>
        <select className="mt-1 w-full rounded border p-2" value={selected.account_type} onChange={(event) => setSelected({ ...selected, account_type: event.target.value })}>{roles.map((role) => <option key={role}>{role}</option>)}</select>
        <label className="label mt-4 block">Ownership</label>
        <select className="mt-1 w-full rounded border p-2" value={selected.ownership} onChange={(event) => setSelected({ ...selected, ownership: event.target.value, owner_id: event.target.value === 'joint' ? null : selected.owner_id })}>
          <option value="joint">Joint</option><option value="individual">Individual</option>
        </select>
        {selected.ownership === 'individual' && <select className="mt-3 w-full rounded border p-2" value={selected.owner_id || ''} onChange={(event) => setSelected({ ...selected, owner_id: event.target.value })} required>
          <option value="">Select household member</option>{members.map((member) => <option value={member.id} key={member.id}>{member.display_name}</option>)}
        </select>}
        <label className="label mt-4 block">Balance</label>
        <input className="mt-1 w-full rounded border p-2" type="number" step="0.01" value={balance} onChange={(event) => setBalance(event.target.value)} required />
        <div className="mt-6 flex justify-between"><button type="button" onClick={() => setDeleting(true)} className="text-red-700">Delete account</button><button className="rounded bg-navy px-4 py-2 text-white">Save</button></div>
        {deleting && <div className="mt-4 rounded bg-red-50 p-3 text-sm text-red-800">Permanently delete this account and its local transactions?<div className="mt-2 flex justify-end gap-2"><button type="button" onClick={() => setDeleting(false)}>Cancel</button><button type="button" className="rounded bg-red-700 px-3 py-1 text-white" onClick={remove}>Delete</button></div></div>}
      </form>
    </div>}
  </Protected>;
}
