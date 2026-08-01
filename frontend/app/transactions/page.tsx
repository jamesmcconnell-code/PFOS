'use client';

import { useCallback, useEffect, useState } from 'react';
import { api, money } from '@/lib/api';
import { Protected } from '@/components/protected';

const roles = ['spending', 'income', 'debt', 'brokerage', 'crypto'];
const selectedValues = (event: React.ChangeEvent<HTMLSelectElement>) => Array.from(event.target.selectedOptions, (option) => option.value);

export default function Transactions() {
  const [rows, setRows] = useState<any[]>([]), [categories, setCategories] = useState<any[]>([]), [sources, setSources] = useState<any[]>([]);
  const [search, setSearch] = useState(''), [categoryIds, setCategoryIds] = useState<string[]>([]), [financialRoles, setFinancialRoles] = useState<string[]>([]), [connectionIds, setConnectionIds] = useState<string[]>([]);
  const [transactionType, setTransactionType] = useState(''), [startDate, setStartDate] = useState(''), [endDate, setEndDate] = useState(''), [sort, setSort] = useState('date_desc'), [page, setPage] = useState(1), [total, setTotal] = useState(0), [totalPages, setTotalPages] = useState(1), [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ search, page: String(page), page_size: '25', sort });
      categoryIds.forEach((id) => params.append('category_ids', id)); financialRoles.forEach((role) => params.append('financial_roles', role)); connectionIds.forEach((id) => params.append('connection_ids', id));
      if (transactionType) params.set('transaction_type', transactionType);
      if (startDate) params.set('start_date', startDate);
      if (endDate) params.set('end_date', endDate);
      const result = await api('/transactions?' + params.toString());
      setRows(result.items); setTotal(result.total); setTotalPages(result.total_pages); setError('');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not load transactions'); }
  }, [search, page, sort, categoryIds, financialRoles, connectionIds, transactionType, startDate, endDate]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { api('/categories').then(setCategories); api('/connections').then(setSources); }, []);
  useEffect(() => { const refresh = () => { setPage(1); void load(); }; window.addEventListener('pfos-view-change', refresh); return () => window.removeEventListener('pfos-view-change', refresh); }, [load]);

  function resetPage(setter: (value: any) => void, value: any) { setter(value); setPage(1); }
  async function setTransfer(transaction: any, isInternalTransfer: boolean) {
    try { await api(`/transactions/${transaction.id}/internal-transfer`, { method: 'PATCH', body: JSON.stringify({ is_internal_transfer: isInternalTransfer }) }); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not update transfer status'); }
  }
  async function setPlannerFlag(transaction: any, changes: Record<string, boolean>) {
    try { await api(`/transactions/${transaction.id}/planner-flags`, { method: 'PATCH', body: JSON.stringify(changes) }); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not update planner flags'); }
  }
  return <Protected><h1 className="text-3xl font-bold">Transactions</h1><p className="mt-1 text-slate-500">Search and filter your transaction history without moving data into the browser.</p>
    <section className="card mt-5"><input className="w-full rounded-lg border bg-white p-3" placeholder="Search description…" value={search} onChange={(event) => resetPage(setSearch, event.target.value)}/><div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <label className="text-sm"><span className="label block">Categories</span><select multiple className="mt-1 min-h-28 w-full rounded border p-2" value={categoryIds} onChange={(event) => resetPage(setCategoryIds, selectedValues(event))}>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
      <label className="text-sm"><span className="label block">Financial roles</span><select multiple className="mt-1 min-h-28 w-full rounded border p-2" value={financialRoles} onChange={(event) => resetPage(setFinancialRoles, selectedValues(event))}>{roles.map((role) => <option key={role} value={role} className="capitalize">{role}</option>)}</select></label>
      <label className="text-sm"><span className="label block">Connected sources</span><select multiple className="mt-1 min-h-28 w-full rounded border p-2" value={connectionIds} onChange={(event) => resetPage(setConnectionIds, selectedValues(event))}>{sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label>
      <div className="space-y-3"><label className="text-sm"><span className="label block">From date</span><input type="date" className="mt-1 w-full rounded border p-2" value={startDate} max={endDate || undefined} onChange={(event) => resetPage(setStartDate, event.target.value)}/></label><label className="text-sm"><span className="label block">To date</span><input type="date" className="mt-1 w-full rounded border p-2" value={endDate} min={startDate || undefined} onChange={(event) => resetPage(setEndDate, event.target.value)}/></label></div>
      <div className="space-y-3"><label className="text-sm"><span className="label block">Transaction type</span><select className="mt-1 w-full rounded border p-2" value={transactionType} onChange={(event) => resetPage(setTransactionType, event.target.value)}><option value="">All activity</option><option value="credit">Credit (+)</option><option value="debit">Debit (-)</option></select></label><label className="text-sm"><span className="label block">Sort</span><select className="mt-1 w-full rounded border p-2" value={sort} onChange={(event) => resetPage(setSort, event.target.value)}><option value="date_desc">Newest first</option><option value="date_asc">Oldest first</option><option value="amount_desc">Highest amount</option><option value="amount_asc">Lowest amount</option></select></label><button type="button" onClick={() => { setCategoryIds([]); setFinancialRoles([]); setConnectionIds([]); setTransactionType(''); setStartDate(''); setEndDate(''); setSort('date_desc'); setPage(1); }} className="text-sm text-slate-600 underline">Clear filters</button></div>
    </div><p className="mt-3 text-xs text-slate-500">Use Ctrl/Cmd-click to select more than one option.</p></section>
    {error && <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <div className="mt-4 flex items-center justify-between text-sm text-slate-500"><span>{total.toLocaleString()} matching transactions</span><span>Page {page} of {totalPages}</span></div>
    <div className="card mt-3 overflow-x-auto p-0"><table className="w-full text-left text-sm"><thead className="border-b text-slate-500"><tr><th className="p-4">Date</th><th>Description</th><th>Category / source</th><th>Amount</th><th>Flags</th></tr></thead><tbody>{rows.map((transaction) => <tr className="border-b last:border-0" key={transaction.id}><td className="p-4">{transaction.date}</td><td>{transaction.description}<p className="text-xs text-slate-400">{transaction.account_name} · {transaction.account_type}</p></td><td><p>{transaction.category_name || 'Uncategorized'}</p><p className="text-xs text-slate-400">{transaction.source_name}</p></td><td className={Number(transaction.amount) < 0 ? 'text-red-600' : 'text-emerald-600'}>{money(transaction.amount)}</td><td>{transaction.is_pending && 'Pending '}{transaction.is_essential && 'Essential '}{transaction.is_recurring && 'Recurring'}<button onClick={() => void setTransfer(transaction, !transaction.is_internal_transfer)} className="mt-1 block text-xs text-slate-500 underline">{transaction.is_internal_transfer ? 'Internal transfer · undo' : 'Mark internal transfer'}</button><div className="mt-2 flex flex-wrap gap-2"><button onClick={() => void setPlannerFlag(transaction,{is_expected:!transaction.is_expected})} className={`text-xs underline ${transaction.is_expected ? 'text-emerald-700' : 'text-slate-500'}`}>{transaction.is_expected ? 'Expected · undo' : 'Mark expected'}</button><button onClick={() => void setPlannerFlag(transaction,{is_annual:!transaction.is_annual})} className={`text-xs underline ${transaction.is_annual ? 'text-emerald-700' : 'text-slate-500'}`}>{transaction.is_annual ? 'Annual · undo' : 'Mark annual'}</button>{Number(transaction.amount)>0 && <button onClick={() => void setPlannerFlag(transaction,{is_refund:!transaction.is_refund})} className={`text-xs underline ${transaction.is_refund ? 'text-emerald-700' : 'text-slate-500'}`}>{transaction.is_refund ? 'Refund · undo' : 'Mark refund'}</button>}</div></td></tr>)}{!rows.length && <tr><td className="p-5 text-slate-500" colSpan={5}>No transactions match these filters.</td></tr>}</tbody></table></div>
    <div className="mt-4 flex justify-end gap-2"><button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded border px-3 py-2 text-sm disabled:opacity-50">Previous</button><button disabled={page >= totalPages} onClick={() => setPage(page + 1)} className="rounded border px-3 py-2 text-sm disabled:opacity-50">Next</button></div>
  </Protected>;
}
