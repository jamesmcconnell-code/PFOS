'use client';

import { useEffect, useState } from 'react';
import { api, money } from '@/lib/api';
import { Protected } from '@/components/protected';

export default function Dashboard() {
  const [data, setData] = useState<any>();
  useEffect(() => { const load = () => api('/dashboard').then(setData).catch(() => {}); load(); window.addEventListener('pfos-view-change', load); return () => window.removeEventListener('pfos-view-change', load); }, []);
  const cards = [['Net worth','net_worth'],['Cash available','cash_available'],['Debt total','debt_total'],['Monthly savings','monthly_savings']];
  return <Protected><header><p className="label">Overview</p><h1 className="text-3xl font-bold">Financial command center</h1></header>{!data ? <p className="mt-8">Loading…</p> : <><section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{cards.map(([label,key]) => <div className="card" key={key}><p className="label">{label}</p><p className="metric mt-2">{money(data[key])}</p></div>)}</section><section className="mt-6 grid gap-5 lg:grid-cols-3"><div className="card"><h2 className="font-semibold">This month</h2><dl className="mt-4 space-y-3 text-sm"><div className="flex justify-between"><dt>Income</dt><dd>{money(data.monthly_income)}</dd></div><div className="flex justify-between"><dt>Expenses</dt><dd>{money(data.monthly_expenses)}</dd></div><div className="flex justify-between font-semibold"><dt>Savings rate</dt><dd>{data.savings_rate}%</dd></div></dl></div><div className="card"><h2 className="font-semibold">Crypto investments</h2>{data.crypto_assets?.length ? data.crypto_assets.map((asset:any) => <div className="mt-3 flex justify-between text-sm" key={asset.symbol}><span>{asset.symbol}</span><b>{Number(asset.amount).toLocaleString(undefined,{maximumFractionDigits:8})}</b></div>) : <p className="mt-3 text-sm text-slate-500">No crypto assets linked.</p>}</div><div className="card"><h2 className="font-semibold">Goals</h2>{data.goals.map((goal:any) => <div className="mt-4" key={goal.id}><div className="flex justify-between text-sm"><span>{goal.name}</span><span>{goal.progress}%</span></div><div className="mt-2 h-2 overflow-hidden rounded bg-slate-100"><div className="h-full bg-mint" style={{width:`${Math.min(goal.progress,100)}%`}}/></div></div>)}</div></section></>}</Protected>;
}
