'use client';

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { Protected } from '@/components/protected';
import { loadViewState, saveViewState } from '@/lib/persistent-view';
import { useSimpleMode } from '@/lib/simple-mode';
import { DetailedReports, ReportsSkeleton, SimpleReports } from '@/components/reports/reports-dashboard';

const choices=['1M','3M','6M','YTD','1Y','All'] as const;
export default function ReportsPage(){const simpleMode=useSimpleMode(),[timeframe,setTimeframe]=useState<typeof choices[number]>('3M'),[data,setData]=useState<any>(),[error,setError]=useState(''),[ready,setReady]=useState(false);const restore=useCallback(()=>{const state=loadViewState('reports',{timeframe:'3M'});setTimeframe(state.timeframe as typeof choices[number]);setData(undefined);setReady(true);},[]);const load=useCallback(()=>api(`/reports?timeframe=${timeframe}`).then(result=>{setData(result);setError('');}).catch(caught=>setError(caught instanceof Error?caught.message:'Could not load reports')),[timeframe]);useEffect(()=>{restore();window.addEventListener('pfos-view-change',restore);return()=>window.removeEventListener('pfos-view-change',restore);},[restore]);useEffect(()=>{if(ready)void load();},[ready,load]);useEffect(()=>{if(ready)saveViewState('reports',{timeframe});},[ready,timeframe]);return <Protected><header className="flex flex-wrap items-end justify-between gap-4"><div><p className="label">Insights</p><h1 className="text-3xl font-bold">Reports</h1><p className="mt-1 text-slate-500">Understand your household’s progress over time.</p></div><div className="flex rounded-xl border bg-white p-1" aria-label="Report timeframe">{choices.map(choice=><button type="button" key={choice} onClick={()=>setTimeframe(choice)} aria-pressed={timeframe===choice} className={`rounded-lg px-3 py-2 text-sm ${timeframe===choice?'bg-navy text-white shadow-sm':'text-slate-600 hover:bg-slate-50'}`}>{choice}</button>)}</div></header>{error&&<p className="mt-5 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>}{!data?<ReportsSkeleton/>:simpleMode?<SimpleReports data={data}/>:<DetailedReports data={data}/>}</Protected>}
