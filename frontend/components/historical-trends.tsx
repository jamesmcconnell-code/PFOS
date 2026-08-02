'use client';

import { useCallback, useEffect, useState } from 'react';
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, money } from '@/lib/api';

type TrendPoint = {
  month: string; label: string; monthly_income: number; monthly_expenses: number; automated_savings: number;
  spending_net_cash_flow: number; monthly_savings: number; savings_rate: number; monthly_sources: any[];
};

const series = [
  { key: 'monthly_income', label: 'Income', color: 'var(--chart-income)', kind: 'bar' },
  { key: 'monthly_expenses', label: 'Expenses', color: 'var(--chart-expense)', kind: 'bar' },
  { key: 'automated_savings', label: 'Automated savings', color: 'var(--chart-savings)', kind: 'bar' },
  { key: 'spending_net_cash_flow', label: 'Spending cash flow', color: 'var(--chart-cash-flow)', kind: 'line' },
  { key: 'monthly_savings', label: 'Monthly savings', color: 'var(--chart-monthly-savings)', kind: 'line' },
  { key: 'savings_rate', label: 'Savings rate', color: 'var(--chart-rate)', kind: 'rate' },
] as const;

function status(value: number) { return value > 0 ? 'text-emerald-700' : value < 0 ? 'text-rose-700' : 'text-slate-600'; }

function TrendTooltip({ active, payload }: any) {
  const point: TrendPoint | undefined = active ? payload?.[0]?.payload : undefined;
  if (!point) return null;
  return <div className="min-w-52 rounded-xl border border-slate-200 bg-white p-3 shadow-lg"><p className="font-semibold">{point.label}</p><div className="mt-2 space-y-1 text-xs">{series.map((item) => <div className="flex justify-between gap-4" key={item.key}><span className="text-slate-600">{item.label}</span><b className={status(Number(point[item.key]))}>{item.kind === 'rate' ? `${point.savings_rate}%` : money(point[item.key])}</b></div>)}</div><p className="mt-2 text-[11px] text-slate-400">Click this month for account sources.</p></div>;
}

export function HistoricalTrends() {
  const [points, setPoints] = useState<TrendPoint[]>([]), [months, setMonths] = useState(6), [selected, setSelected] = useState<TrendPoint | null>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>(() => Object.fromEntries(series.map((item) => [item.key, true])));
  const load = useCallback(() => api(`/finance/trends?months=${months}`).then((result) => setPoints(result.series)).catch(() => setPoints([])), [months]);
  useEffect(() => { void load(); window.addEventListener('pfos-view-change', load); return () => window.removeEventListener('pfos-view-change', load); }, [load]);
  const sourceRows = selected?.monthly_sources || [];
  return <section className="card mt-6"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">Historical trends</h2><p className="mt-1 text-sm text-slate-500">Monthly cash-flow and savings movement. Click a month for account sources.</p></div><label className="text-sm text-slate-600">Period <select className="ml-2 rounded border p-2" value={months} onChange={(event) => { setMonths(Number(event.target.value)); setSelected(null); }}><option value={3}>3 months</option><option value={6}>6 months</option><option value={12}>12 months</option></select></label></div>
    <div className="mt-4 flex flex-wrap gap-2" aria-label="Trend series visibility">{series.map((item) => <button type="button" key={item.key} aria-pressed={visible[item.key]} onClick={() => setVisible((current) => ({ ...current, [item.key]: !current[item.key] }))} className={`rounded-full border px-3 py-1.5 text-xs ${visible[item.key] ? 'border-slate-300 bg-slate-50 text-slate-800' : 'border-slate-200 text-slate-400'}`}><span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: item.color }}/>{item.label}</button>)}</div>
    {points.length ? <div className="mt-5 h-80"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={points} margin={{ top: 12, right: 12, left: -12, bottom: 0 }} onClick={(chart: any) => { const point=chart?.activePayload?.[0]?.payload as TrendPoint | undefined; if (point) setSelected(point); }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--chart-grid)"/><XAxis dataKey="label" tick={{ fontSize: 12, fill: 'var(--chart-tick)' }} axisLine={false} tickLine={false}/><YAxis yAxisId="money" tickFormatter={(value) => `$${Math.round(value / 1000)}k`} tick={{ fontSize: 12, fill: 'var(--chart-tick)' }} axisLine={false} tickLine={false}/><YAxis yAxisId="rate" orientation="right" tickFormatter={(value) => `${value}%`} tick={{ fontSize: 12, fill: 'var(--chart-tick)' }} axisLine={false} tickLine={false}/><Tooltip content={<TrendTooltip />}/>{visible.monthly_income && <Bar yAxisId="money" dataKey="monthly_income" fill="var(--chart-income)" radius={[4,4,0,0]} maxBarSize={28}/>} {visible.monthly_expenses && <Bar yAxisId="money" dataKey="monthly_expenses" fill="var(--chart-expense)" radius={[4,4,0,0]} maxBarSize={28}/>} {visible.automated_savings && <Bar yAxisId="money" dataKey="automated_savings" fill="var(--chart-savings)" radius={[4,4,0,0]} maxBarSize={28}/>} {visible.spending_net_cash_flow && <Line yAxisId="money" type="monotone" dataKey="spending_net_cash_flow" stroke="var(--chart-cash-flow)" strokeWidth={2} dot={{ r: 3 }}/>} {visible.monthly_savings && <Line yAxisId="money" type="monotone" dataKey="monthly_savings" stroke="var(--chart-monthly-savings)" strokeWidth={3} dot={{ r: 3 }}/>} {visible.savings_rate && <Line yAxisId="rate" type="monotone" dataKey="savings_rate" stroke="var(--chart-rate)" strokeWidth={2} strokeDasharray="4 3" dot={{ r: 3 }}/>}</ComposedChart></ResponsiveContainer></div> : <p className="mt-6 text-sm text-slate-500">No transaction history is available for this period.</p>}
    {selected && <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="flex items-center justify-between gap-3"><div><h3 className="font-semibold">{selected.label} account sources</h3><p className="text-xs text-slate-500">Only accounts that affected this month’s cash-flow metrics are shown.</p></div><button type="button" onClick={() => setSelected(null)} className="text-sm text-slate-500 underline">Close</button></div>{sourceRows.length ? <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><thead className="text-slate-500"><tr><th className="pb-2">Account / source</th><th className="pb-2 text-right">Income</th><th className="pb-2 text-right">Expenses</th><th className="pb-2 text-right">Auto savings</th><th className="pb-2 text-right">Cash flow</th></tr></thead><tbody>{sourceRows.map((source: any) => <tr className="border-t border-slate-200" key={source.account_id}><td className="py-2"><b className="block">{source.account_name}</b><span className="text-slate-400">{source.source_name}</span></td><td className={`py-2 text-right ${status(Number(source.income))}`}>{money(source.income)}</td><td className={`py-2 text-right ${source.expenses ? 'text-rose-700' : ''}`}>{money(source.expenses)}</td><td className={`py-2 text-right ${status(Number(source.automated_savings))}`}>{money(source.automated_savings)}</td><td className={`py-2 text-right ${status(Number(source.spending_cash_flow))}`}>{money(source.spending_cash_flow)}</td></tr>)}</tbody></table></div> : <p className="mt-3 text-sm text-slate-500">No qualifying account activity for this month.</p>}</div>}
  </section>;
}
