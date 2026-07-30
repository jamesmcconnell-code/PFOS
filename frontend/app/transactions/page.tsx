'use client';

import { useEffect, useState } from 'react';
import { api, money } from '@/lib/api';
import { Protected } from '@/components/protected';

export default function Transactions() {
  const [rows, setRows] = useState<any[]>([]), [search, setSearch] = useState('');
  useEffect(() => { const load = () => api('/transactions?search=' + encodeURIComponent(search)).then(setRows); load(); window.addEventListener('pfos-view-change', load); return () => window.removeEventListener('pfos-view-change', load); }, [search]);
  return <Protected><h1 className="text-3xl font-bold">Transactions</h1><input className="mt-5 w-full max-w-md rounded-lg border bg-white p-3" placeholder="Search description…" value={search} onChange={(event) => setSearch(event.target.value)}/><div className="card mt-5 overflow-x-auto p-0"><table className="w-full text-left text-sm"><thead className="border-b text-slate-500"><tr><th className="p-4">Date</th><th>Description</th><th>Category / source</th><th>Amount</th><th>Flags</th></tr></thead><tbody>{rows.map((transaction) => <tr className="border-b last:border-0" key={transaction.id}><td className="p-4">{transaction.date}</td><td>{transaction.description}<p className="text-xs text-slate-400">{transaction.account_name}</p></td><td><p>{transaction.category_name || 'Uncategorized'}</p><p className="text-xs text-slate-400">{transaction.source_name}</p></td><td className={Number(transaction.amount) < 0 ? 'text-red-600' : 'text-emerald-600'}>{money(transaction.amount)}</td><td>{transaction.is_pending && 'Pending '}{transaction.is_essential && 'Essential '}{transaction.is_recurring && 'Recurring'}</td></tr>)}</tbody></table></div></Protected>;
}
