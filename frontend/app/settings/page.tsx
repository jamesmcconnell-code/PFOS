'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { Protected } from '@/components/protected';

export default function Settings() {
  const [name, setName] = useState(''), [email, setEmail] = useState(''), [password, setPassword] = useState('');
  const [memberName, setMemberName] = useState(''), [memberEmail, setMemberEmail] = useState(''), [memberPassword, setMemberPassword] = useState('');
  const [message, setMessage] = useState(''), [members, setMembers] = useState<any[]>([]);
  const loadMembers = () => api('/household/members').then(setMembers);

  useEffect(() => { api('/auth/me').then((profile) => { setName(profile.display_name); setEmail(profile.email); }); void loadMembers(); }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    try { await api('/auth/me', { method: 'PATCH', body: JSON.stringify({ display_name: name, email, password: password || undefined }) }); setPassword(''); setMessage('Profile saved.'); }
    catch (caught) { setMessage(caught instanceof Error ? caught.message : 'Could not save profile'); }
  }
  async function addMember(event: React.FormEvent) {
    event.preventDefault();
    try { await api('/household/members', { method: 'POST', body: JSON.stringify({ display_name: memberName, email: memberEmail, password: memberPassword }) }); setMemberName(''); setMemberEmail(''); setMemberPassword(''); setMessage('Household member added. They can now sign in with their email and password.'); await loadMembers(); }
    catch (caught) { setMessage(caught instanceof Error ? caught.message : 'Could not add household member'); }
  }

  return <Protected><h1 className="text-3xl font-bold">Settings</h1>{message && <p className="mt-4 rounded-xl bg-slate-100 p-3 text-sm" role="status">{message}</p>}
    <form onSubmit={save} className="card mt-6 max-w-xl"><h2 className="font-semibold">Your profile</h2><label className="label mt-4 block">Display name</label><input className="mt-1 w-full rounded border p-2" value={name} onChange={(event) => setName(event.target.value)} required/><label className="label mt-4 block">Email</label><input className="mt-1 w-full rounded border p-2" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required/><label className="label mt-4 block">New password</label><input className="mt-1 w-full rounded border p-2" type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Leave blank to keep current password"/><button className="mt-5 rounded bg-navy px-4 py-2 text-white">Save profile</button></form>
    <section className="card mt-6 max-w-xl"><h2 className="font-semibold">Household members</h2><p className="mt-1 text-sm text-slate-500">Each member has a separate sign-in and can own individual accounts.</p><ul className="mt-4 space-y-2 text-sm">{members.map((member) => <li key={member.id} className="flex justify-between rounded bg-slate-50 p-2"><span>{member.display_name}</span><span className="text-slate-500">{member.role}</span></li>)}</ul>
      <form onSubmit={addMember} className="mt-5 border-t pt-5"><h3 className="font-medium">Add household member</h3><input className="mt-3 w-full rounded border p-2" placeholder="Display name" value={memberName} onChange={(event) => setMemberName(event.target.value)} required/><input className="mt-3 w-full rounded border p-2" type="email" placeholder="Email" value={memberEmail} onChange={(event) => setMemberEmail(event.target.value)} required/><input className="mt-3 w-full rounded border p-2" type="password" minLength={8} placeholder="Temporary password (8+ characters)" value={memberPassword} onChange={(event) => setMemberPassword(event.target.value)} required/><button className="mt-4 rounded bg-navy px-4 py-2 text-white">Add member</button></form>
    </section>
  </Protected>;
}
