'use client';

import { useEffect, useState } from 'react';
import { api, money } from '@/lib/api';
import { Protected } from '@/components/protected';
import { HistoricalTrends } from '@/components/historical-trends';

function MetricSources({ sources, metric, label }: { sources: any[]; metric: string; label: string }) {
  const rows = sources.filter((source) => Number(source[metric]) !== 0);
  if (!rows.length) return null;
  return <details className="border-t border-slate-100 pt-2 text-xs"><summary className="cursor-pointer text-slate-600">{label} sources ({rows.length})</summary><ul className="mt-2 space-y-2">{rows.map((source) => <li className="flex items-start justify-between gap-3" key={source.account_id}><span className="min-w-0"><b className="block truncate text-slate-700">{source.account_name}</b><span className="text-slate-400">{source.source_name}</span></span><span className="shrink-0 font-medium text-slate-700">{money(source[metric])}</span></li>)}</ul></details>;
}

function MonthMetric({ label, value, kind = 'positive' }: { label: string; value: number; kind?: 'positive' | 'expense' | 'rate' }) {
  const favorable = kind === 'expense' ? value === 0 : value > 0;
  const neutral = value === 0;
  const tone = neutral ? 'bg-slate-50 text-slate-600' : favorable ? 'bg-emerald-50 text-emerald-800' : 'bg-rose-50 text-rose-800';
  const status = neutral ? 'Neutral' : favorable ? 'Favorable' : 'Needs attention';
  return <div className={`flex items-center justify-between gap-3 rounded-lg px-2 py-2 ${tone}`}><dt>{label}</dt><dd className="flex items-center gap-2 font-medium"><span className="hidden text-[11px] sm:inline">{status}</span>{kind === 'rate' ? `${value}%` : money(value)}</dd></div>;
}

export default function Dashboard() {
  const [data, setData] = useState<any>();
  const [period, setPeriod] = useState<'calendar_month' | 'rolling_30_days'>('calendar_month');
  useEffect(() => {
    const load = () => api(`/dashboard?period=${period}`).then(setData).catch(() => {});
    load();
    const refresh = window.setInterval(load, 30000);
    window.addEventListener('pfos-view-change', load);
    window.addEventListener('focus', load);
    return () => { window.clearInterval(refresh); window.removeEventListener('pfos-view-change', load); window.removeEventListener('focus', load); };
  }, [period]);
  const cards = [['Net worth','net_worth'],['Cash available','cash_available'],['Debt total','debt_total'],[period === 'rolling_30_days' ? '30-day savings' : 'Monthly savings','monthly_savings']];
  const sources = data?.monthly_sources || [];
  const rolling = period === 'rolling_30_days';
  return <Protected><header><p className="label">Overview</p><h1 className="text-3xl font-bold">Financial command center</h1></header>{!data ? <p className="mt-8">Loading…</p> : <><section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{cards.map(([label,key]) => <div className="card" key={key}><p className="label">{label}</p><p className="metric mt-2">{money(data[key])}</p></div>)}</section><section className="mt-6 grid gap-5 lg:grid-cols-3"><div className="card"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">This month</h2><div className="flex rounded-lg border p-0.5 text-xs" aria-label="This month reporting period"><button type="button" onClick={() => setPeriod('calendar_month')} aria-pressed={!rolling} className={`rounded-md px-2 py-1.5 ${!rolling ? 'bg-navy text-white' : 'text-slate-600'}`}>Calendar month</button><button type="button" onClick={() => setPeriod('rolling_30_days')} aria-pressed={rolling} className={`rounded-md px-2 py-1.5 ${rolling ? 'bg-navy text-white' : 'text-slate-600'}`}>Last 30 days</button></div></div><p className="mt-2 text-xs text-slate-400">{rolling ? `${data.period_start} through ${data.period_end}` : 'Current calendar month'} · Updates automatically</p><dl className="mt-4 space-y-2 text-sm"><MonthMetric label="Income" value={data.monthly_income}/><MetricSources sources={sources} metric="income" label="Income" /><MonthMetric label="Expenses" value={data.monthly_expenses} kind="expense"/><MetricSources sources={sources} metric="expenses" label="Expense" /><MonthMetric label="Automated savings" value={data.automated_savings}/><MetricSources sources={sources} metric="automated_savings" label="Automated savings" /><MonthMetric label="Spending cash flow" value={data.spending_net_cash_flow}/><MetricSources sources={sources} metric="spending_cash_flow" label="Cash-flow" /><MonthMetric label="Monthly savings" value={data.monthly_savings}/><MonthMetric label="Savings rate" value={data.savings_rate} kind="rate"/><p className="pt-1 text-xs text-slate-400">Savings rate uses this period’s income and savings above.</p></dl></div><div className="card"><h2 className="font-semibold">Crypto investments</h2>{data.crypto_assets?.length ? data.crypto_assets.map((asset:any) => <div className="mt-3 flex justify-between text-sm" key={asset.symbol}><span>{Number(asset.quantity).toLocaleString(undefined,{maximumFractionDigits:8})} {asset.symbol}</span><b>{asset.quote_available ? money(asset.usd_value) : 'Quote unavailable'}</b></div>) : <p className="mt-3 text-sm text-slate-500">No crypto assets linked.</p>}</div><div className="card"><h2 className="font-semibold">Goals</h2>{data.goals.map((goal:any) => <div className="mt-4" key={goal.id}><div className="flex justify-between text-sm"><span>{goal.name}</span><span>{goal.progress}%</span></div><div className="mt-2 h-2 overflow-hidden rounded bg-slate-100"><div className="h-full bg-mint" style={{width:`${Math.min(goal.progress,100)}%`}}/></div></div>)}</div></section><HistoricalTrends /></>}</Protected>;
}
