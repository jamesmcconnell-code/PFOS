'use client';
import { FinancialValue } from "@/components/financial-value";

import { useEffect, useState } from 'react';
import { loadViewState, saveViewState } from '@/lib/persistent-view';
import { plannerSummary } from '@/lib/planner-summary';
import { api, money } from '@/lib/api';
import { Protected } from '@/components/protected';
import { HistoricalTrends } from '@/components/historical-trends';

function MetricSources({ sources, metric, label }: { sources: any[]; metric: string; label: string }) {
  const rows = sources.filter((source) => Number(source[metric]) !== 0);
  if (!rows.length) return null;
  return <details className="border-t border-slate-100 pt-2 text-xs"><summary className="cursor-pointer text-slate-600">{label} sources ({rows.length})</summary><ul className="mt-2 space-y-2">{rows.map((source) => <li className="flex items-start justify-between gap-3" key={source.account_id}><span className="min-w-0"><b className="block truncate text-slate-700">{source.account_name}</b><span className="text-slate-400">{source.source_name}</span></span><span className="shrink-0 font-medium text-slate-700"><FinancialValue>{money(source[metric])}</FinancialValue></span></li>)}</ul></details>;
}

function MonthMetric({ label, value, kind = 'positive' }: { label: string; value: number; kind?: 'positive' | 'expense' | 'rate' }) {
  const favorable = kind === 'expense' ? value === 0 : value > 0;
  const neutral = value === 0;
  const tone = neutral ? 'bg-slate-50 text-slate-600' : favorable ? 'bg-emerald-50 text-emerald-800' : 'bg-rose-50 text-rose-800';
  const status = neutral ? 'Neutral' : favorable ? 'Favorable' : 'Needs attention';
  return <div className={`flex items-center justify-between gap-3 rounded-lg px-2 py-2 ${tone}`}><dt>{label}</dt><dd className="flex items-center gap-2 font-medium"><span className="hidden text-[11px] sm:inline">{status}</span><FinancialValue>{kind === 'rate' ? `${value}%` : money(value)}</FinancialValue></dd></div>;
}

export default function Dashboard() {
  const [data, setData] = useState<any>();
  const [planner,setPlanner]=useState<any>();
  const [error,setError]=useState('');
  const [scopeName,setScopeName]=useState('Joint household');
  useEffect(() => {
    let active=true, request=0;
    const load = async () => {
      const current=++request;
      const anchor=new Date().toLocaleDateString('en-CA');
      try {
        const [dashboard,available]=await Promise.all([api('/dashboard?period=calendar_month'),api(`/available-cash-planner?period=monthly&anchor_date=${anchor}`)]);
        if(active && current===request){setData(dashboard);setPlanner(available);setError('');}
      } catch {if(active && current===request){setPlanner(undefined);setError('Could not refresh Available Cash figures. Retrying automatically.');}}
    };
    const updateScopeLabel=()=>{const selected=localStorage.getItem('pfos_view_user_id');if(!selected){setScopeName('Joint household');return;}void api('/household/members').then((members:any[])=>setScopeName(members.find((member:any)=>member.id===selected)?.display_name||'Selected user')).catch(()=>setScopeName('Selected user'));};
    const handleViewChange=()=>{setPlanner(undefined);setData(undefined);load();updateScopeLabel();};
    load();
    updateScopeLabel();
    const refresh = window.setInterval(load, 30000);
    window.addEventListener('pfos-view-change', handleViewChange);
    window.addEventListener('focus', load);
    return () => { active=false; window.clearInterval(refresh); window.removeEventListener('pfos-view-change', handleViewChange); window.removeEventListener('focus', load); };
  }, []);
  const cards = [['Net worth','net_worth'],['Cash available','cash_available'],['Debt total','debt_total'],['Monthly savings','monthly_savings']];
  const summary=plannerSummary(planner);
  const sources=summary.sources;
  return <Protected><header><p className="label">Overview</p><h1 className="text-3xl font-bold">Financial command center</h1></header>{error&&<p role="alert" className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}{!data ? <p className="mt-8">Loading…</p> : <><section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{cards.map(([label,key]) => <div className="card" key={key}><p className="label">{label}</p><p className="metric mt-2"><FinancialValue>{key==='monthly_savings'?(planner?money(summary.savings):'—'):money(data[key])}</FinancialValue></p></div>)}</section><section className="mt-6 grid gap-5 lg:grid-cols-3"><div className="card"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">This month</h2><p className="mt-1 text-xs text-slate-500">Viewing: {scopeName}</p></div><a href="/available-cash" onClick={()=>saveViewState('available-cash',{...loadViewState('available-cash',{}),period:'monthly',anchorDate:new Date().toLocaleDateString('en-CA')})} className="text-xs font-medium text-navy underline">View monthly planner</a></div><p className="mt-2 text-xs text-slate-400">{planner?`${planner.period_start} through ${planner.period_end}`:'Monthly planner'} · Updates automatically</p>{!planner?<p className="mt-4 text-sm text-slate-500">{error?'Planner figures unavailable.':'Loading planner…'}</p>:<dl className="mt-4 space-y-2 text-sm"><MonthMetric label="Income" value={summary.income}/><MetricSources sources={sources} metric="income" label="Income" /><MonthMetric label="Expenses" value={summary.expenses} kind="expense"/><MetricSources sources={sources} metric="expenses" label="Expense" /><MonthMetric label="Automated savings" value={summary.automatedSavings}/><MetricSources sources={sources} metric="automated_savings" label="Automated savings" /><MonthMetric label="Spending cash flow" value={summary.spendingCashFlow}/><MetricSources sources={sources} metric="spending_cash_flow" label="Cash-flow" /><MonthMetric label="Monthly savings" value={summary.savings}/><MonthMetric label="Savings rate" value={summary.savingsRate} kind="rate"/><p className="pt-1 text-xs text-slate-400">Uses Available Cash’s monthly calculations and actual automated savings, before any what-if adjustment. Savings rate includes paycheck income plus automated savings.</p></dl>}</div><div className="card"><h2 className="font-semibold">Crypto investments</h2>{data.crypto_assets?.length ? data.crypto_assets.map((asset:any) => <div className="mt-3 flex justify-between text-sm" key={asset.symbol}><span><FinancialValue>{Number(asset.quantity).toLocaleString(undefined,{maximumFractionDigits:8})}</FinancialValue> {asset.symbol}</span><b><FinancialValue>{asset.quote_available ? money(asset.usd_value) : 'Quote unavailable'}</FinancialValue></b></div>) : <p className="mt-3 text-sm text-slate-500">No crypto assets linked.</p>}</div><div className="card"><h2 className="font-semibold">Goals</h2>{data.goals.map((goal:any) => <div className="mt-4" key={goal.id}><div className="flex justify-between text-sm"><span>{goal.name}</span><span><FinancialValue>{goal.progress}</FinancialValue>%</span></div><div className="mt-2 h-2 overflow-hidden rounded bg-slate-100"><div className="h-full bg-mint" style={{width:`${Math.min(goal.progress,100)}%`}}/></div></div>)}</div></section><HistoricalTrends /></>}</Protected>;
}
