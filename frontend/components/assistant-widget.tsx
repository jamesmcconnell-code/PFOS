'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Calculator, ExternalLink, HelpCircle, LoaderCircle, MessageCircle, Send, Trash2, X } from 'lucide-react';
import { api, money } from '@/lib/api';
import { FinancialOptionValue, FinancialValue } from '@/components/financial-value';
import { SESSION_EXPIRED_EVENT } from '@/lib/auth-session';
import { findAssistantHelp, suggestedAssistantTopics } from '@/lib/assistant-help';

type Message = { id: number; role: 'user' | 'assistant'; text: string; href?: string; hrefLabel?: string };
type AssistantOptions = { categories: { id: string; name: string; parent_id: string | null }[]; goals: { id: string; name: string; target_amount: number; current_amount: number; target_date: string | null }[] };
type ScenarioResult = {
  category: { id: string; name: string };
  goal: { id: string; name: string; target_amount: number; current_amount: number; remaining_amount: number; configured_target_date: string | null };
  history: { history_start: string; history_end: string; history_months: number; transaction_count: number; total_spending: number; average_monthly_spending: number };
  baseline: { monthly_savings_estimate: number; one_time_sweep_estimate: number; projected_months: number | null; projected_date: string | null };
  scenario: { monthly_reduction: number; duration_months: number; planned_total_reduction: number; additional_goal_funding_applied: number; projected_months: number | null; projected_date: string | null };
  estimated_months_earlier: number | null;
  assumptions: string[];
  warnings: string[];
};

const welcome: Message = {
  id: 0,
  role: 'assistant',
  text: 'I can explain PFOS features, summarize category spending, and compare a spending-to-savings scenario using PFOS calculations.',
};

export function AssistantWidget() {
  const pathname = usePathname();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const nextMessageId = useRef(1);
  const [signedIn, setSignedIn] = useState(false);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<'help' | 'scenario'>('help');
  const [messages, setMessages] = useState<Message[]>([welcome]);
  const [question, setQuestion] = useState('');
  const [options, setOptions] = useState<AssistantOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState(false);
  const [categoryId, setCategoryId] = useState('');
  const [goalId, setGoalId] = useState('');
  const [reduction, setReduction] = useState('');
  const [duration, setDuration] = useState('12');
  const [historyMonths, setHistoryMonths] = useState('6');
  const [loading, setLoading] = useState(false);
  const [scenario, setScenario] = useState<ScenarioResult | null>(null);

  useEffect(() => {
    const syncAuthentication = () => setSignedIn(Boolean(localStorage.getItem('pfos_token')));
    syncAuthentication();
    window.addEventListener('storage', syncAuthentication);
    window.addEventListener(SESSION_EXPIRED_EVENT, syncAuthentication);
    return () => {
      window.removeEventListener('storage', syncAuthentication);
      window.removeEventListener(SESSION_EXPIRED_EVENT, syncAuthentication);
    };
  }, [pathname]);

  useEffect(() => {
    if (!signedIn) {
      setOpen(false);
      setMessages([welcome]);
      setScenario(null);
      setOptions(null);
      setQuestion('');
      setCategoryId('');
      setGoalId('');
      setReduction('');
    }
  }, [signedIn]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const closeOnOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('pointerdown', closeOnOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  async function loadOptions(): Promise<AssistantOptions | null> {
    if (options) return options;
    setOptionsLoading(true);
    setOptionsError(false);
    try {
      const result = await api('/assistant/options') as AssistantOptions;
      setOptions(result);
      setCategoryId((current) => current || result.categories[0]?.id || '');
      setGoalId((current) => current || result.goals[0]?.id || '');
      return result;
    } catch {
      setOptionsError(true);
      return null;
    } finally {
      setOptionsLoading(false);
    }
  }

  function addMessage(role: Message['role'], text: string, href?: string, hrefLabel?: string) {
    const id = nextMessageId.current++;
    setMessages((current) => [...current, { id, role, text, href, hrefLabel }]);
  }

  async function answerQuestion(rawQuestion: string) {
    const value = rawQuestion.trim();
    if (!value || loading) return;
    setQuestion('');
    addMessage('user', value);
    const normalized = value.toLowerCase();
    const scenarioIntent = /how much sooner|\bsooner\b|if i.{0,120}\b(?:cut|reduce|decrease|lower|spend less)\b|what if.{0,120}\b(?:reduce|decrease|cut|lower|save|spend less)\b|\b(?:reduce|decrease|cut|lower)\b.{0,50}\b(?:spend|spending|shopping|expenses)\b/.test(normalized);
    if (scenarioIntent) {
      setMode('scenario');
      const currentOptions = await loadOptions();
      if (!currentOptions) {
        addMessage('assistant', 'I can model that in PFOS, but could not load the available expense categories and goals. Please try again.');
        return;
      }
      const matchedCategory = currentOptions.categories.slice().sort((a,b)=>b.name.length-a.name.length).find((item)=>normalized.includes(item.name.toLowerCase()));
      const matchedGoal = currentOptions.goals.find((item)=>normalized.includes(item.name.toLowerCase()));
      const amountMatch = value.match(/\$\s*(\d[\d,]*(?:\.\d{1,2})?)/);
      const durationMatch = value.match(/\b(\d{1,3})\s*(months?|mos?)\b/i);
      const yearMatch = value.match(/\b(\d{1,2})\s*years?\b/i);
      const validYearMatch = yearMatch && Number(yearMatch[1]) <= 10;
      if (matchedCategory) setCategoryId(matchedCategory.id);
      if (matchedGoal) setGoalId(matchedGoal.id);
      if (amountMatch) setReduction(amountMatch[1].replaceAll(',',''));
      if (durationMatch) setDuration(durationMatch[1]);
      else if (validYearMatch) setDuration(String(Number(yearMatch[1])*12));
      const missing = [!matchedCategory&&'expense category',!matchedGoal&&'savings goal',!amountMatch&&'monthly reduction amount',!durationMatch&&!validYearMatch&&'duration'].filter(Boolean);
      addMessage('assistant', `I can model that in PFOS.${matchedCategory?` I matched the ${matchedCategory.name} category.`:''}${matchedGoal?` I matched the ${matchedGoal.name} goal.`:''}${amountMatch?` I read ${money(Number(amountMatch[1].replaceAll(',','')))} as the amount.`:''}${durationMatch||validYearMatch?' I filled in the duration.':''} Please review the What If form${missing.length?` and provide the ${missing.join(', ')}${missing.length===1?'':'s'}`:' and confirm the inputs'} before calculating. The calculation will show its assumptions.`);
      return;
    }

    if (/\b(?:how much|average|spend|spending|spent|total)\b/.test(normalized)) {
      const currentOptions = await loadOptions();
      const matchedCategory = currentOptions?.categories
        .slice().sort((a, b) => b.name.length - a.name.length)
        .find((category) => normalized.includes(category.name.toLowerCase()));
      if (matchedCategory) {
        setLoading(true);
        try {
          const result = await api(`/assistant/spending-summary?category_id=${matchedCategory.id}&history_months=${historyMonths}`) as ScenarioResult['history'] & { category_name: string };
          addMessage('assistant', `Across ${result.history_months} completed months (${result.history_start} through ${result.history_end}), PFOS found ${money(result.total_spending)} in ${result.category_name} outflows across ${result.transaction_count} categorized allocations. That averages ${money(result.average_monthly_spending)} per month. This total counts outflows and does not net credits or refunds.`, '/category-tracker', 'Open Category Tracker');
        } catch {
          addMessage('assistant', 'I could not load that category summary right now. Please try again or review it in Category Tracker.', '/category-tracker', 'Open Category Tracker');
        } finally {
          setLoading(false);
        }
        return;
      }
      if (/\b(?:category|shopping|groceries|dining|travel|spend|spending)\b/.test(normalized)) {
        setMode('scenario');
        addMessage('assistant', 'Which expense category should I use? Open What If to choose from the categories in your PFOS household.');
        return;
      }
    }

    const topic = findAssistantHelp(value, pathname);
    if (topic) {
      addMessage('assistant', topic.content, topic.href, `Open ${topic.title}`);
      return;
    }
    addMessage('assistant', 'I could not find a supported answer in the PFOS help guide. Try asking about Available Cash, transactions, category spending, savings rules, goals, accounts, Plaid connections, or the household view.');
  }

  function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void answerQuestion(question);
  }

  async function submitScenario(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!categoryId || !goalId || !reduction || loading) return;
    const category = options?.categories.find((item) => item.id === categoryId);
    const goal = options?.goals.find((item) => item.id === goalId);
    if (!category || !goal) return;
    setLoading(true);
    setScenario(null);
    addMessage('user', `What if I reduce ${category.name} by ${money(Number(reduction))} per month for ${duration} months and put it toward ${goal.name}?`);
    try {
      const result = await api('/assistant/scenario', {
        method: 'POST',
        body: JSON.stringify({ category_id: categoryId, goal_id: goalId, monthly_reduction: Number(reduction), duration_months: Number(duration), history_months: Number(historyMonths) }),
      }) as ScenarioResult;
      setScenario(result);
      const baseline = result.baseline.projected_date ? `about ${result.baseline.projected_date}` : 'not reached within the 100-year projection';
      const changed = result.scenario.projected_date ? `about ${result.scenario.projected_date}` : 'not reached within the 100-year projection';
      const timing = result.estimated_months_earlier === null
        ? 'I could not calculate a date comparison with the available data.'
        : result.estimated_months_earlier > 0
          ? `That is an estimated ${result.estimated_months_earlier} month${result.estimated_months_earlier === 1 ? '' : 's'} sooner.`
          : result.estimated_months_earlier === 0
            ? 'The projected month is unchanged under these assumptions.'
            : `Under these assumptions, the scenario is ${Math.abs(result.estimated_months_earlier)} months later.`;
      addMessage('assistant', `Using the ${result.history.history_months}-month category history and the recent PFOS cash-flow estimate, ${result.goal.name} is projected to reach its target ${baseline} at the current pace and ${changed} in this scenario. ${timing}`);
    } catch {
      addMessage('assistant', 'I could not calculate this scenario. Check that the selected category and goal are still available, then try again.');
    } finally {
      setLoading(false);
    }
  }

  function clearConversation() {
    setMessages([{ ...welcome, id: 0 }]);
    nextMessageId.current = 1;
    setScenario(null);
    setOptions(null);
    setOptionsError(false);
    setQuestion('');
    setCategoryId('');
    setGoalId('');
    setReduction('');
  }

  function useSuggestedQuestion(text: string) {
    void answerQuestion(text);
  }

  if (!signedIn || pathname === '/login') return null;
  const suggestions = suggestedAssistantTopics(pathname);

  return <div ref={rootRef} className="fixed bottom-4 right-4 z-[70] flex flex-col items-end gap-3">
    {open && <section role="dialog" aria-modal="false" aria-labelledby="pfos-assistant-title" className="flex max-h-[min(78vh,44rem)] w-[min(27rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
      <header className="flex items-start justify-between gap-3 bg-navy p-4 text-white">
        <div className="flex items-start gap-3"><span className="rounded-lg bg-white/10 p-2"><MessageCircle size={18}/></span><div><h2 id="pfos-assistant-title" className="font-semibold">PFOS Assistant</h2><p className="mt-1 text-xs text-slate-300">Product help and private planning scenarios</p></div></div>
        <div className="flex gap-1"><button type="button" onClick={clearConversation} className="rounded p-2 text-slate-300 hover:bg-white/10 hover:text-white" aria-label="Clear conversation" title="Clear conversation"><Trash2 size={17}/></button><button type="button" onClick={()=>setOpen(false)} className="rounded p-2 text-slate-300 hover:bg-white/10 hover:text-white" aria-label="Close assistant"><X size={18}/></button></div>
      </header>
      <div className="grid grid-cols-2 border-b bg-slate-50 p-2" aria-label="Assistant mode">
        <button type="button" aria-pressed={mode==='help'} onClick={()=>setMode('help')} className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${mode==='help'?'bg-white text-navy shadow-sm':'text-slate-600'}`}><HelpCircle size={16}/> App help</button>
        <button type="button" aria-pressed={mode==='scenario'} onClick={()=>{setMode('scenario');void loadOptions();}} className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${mode==='scenario'?'bg-white text-navy shadow-sm':'text-slate-600'}`}><Calculator size={16}/> What If</button>
      </div>
      <p className="border-b border-emerald-100 bg-emerald-50 px-4 py-2 text-xs text-emerald-900">Privacy: PFOS computes scenarios in-app. No chat or financial data is sent to an external AI provider.</p>
      <div className="flex-1 space-y-3 overflow-y-auto p-4" role="log" aria-live="polite" aria-relevant="additions">
        {messages.map((message) => <div key={message.id} className={`max-w-[92%] rounded-2xl px-3 py-2.5 text-sm leading-relaxed ${message.role==='user'?'ml-auto rounded-br-sm bg-navy text-white':'rounded-bl-sm bg-slate-100 text-slate-800'}`}>
          <p className="whitespace-pre-wrap"><FinancialValue>{message.text}</FinancialValue></p>
          {message.href&&<Link href={message.href} onClick={()=>setOpen(false)} className={`mt-2 inline-flex items-center gap-1 text-xs font-semibold underline ${message.role==='user'?'text-white':'text-navy'}`}>{message.hrefLabel||'Open in PFOS'} <ExternalLink size={12}/></Link>}
        </div>)}
        {loading&&<p className="flex items-center gap-2 text-xs text-slate-500" role="status"><LoaderCircle size={14} className="animate-spin"/> Calculating with PFOS data…</p>}
      </div>

      {scenario&&<div className="max-h-56 overflow-y-auto border-t bg-slate-50 p-4 text-sm">
        <div className="flex items-start justify-between gap-3"><div><p className="font-semibold">Scenario estimate</p><p className="text-xs text-slate-500"><FinancialValue>{scenario.goal.name} · recorded {money(scenario.goal.current_amount)} of {money(scenario.goal.target_amount)}</FinancialValue></p></div><span className="rounded-full bg-amber-100 px-2 py-1 text-[10px] font-semibold uppercase text-amber-900">Estimate</span></div>
        <div className="mt-3 grid grid-cols-2 gap-2"><div className="rounded-lg bg-white p-3"><p className="text-xs text-slate-500">Current pace</p><p className="mt-1 font-semibold"><FinancialValue>{scenario.baseline.projected_date||'Not reached'}</FinancialValue></p><p className="text-xs text-slate-500"><FinancialValue>{scenario.baseline.projected_months??'Over 100'} months</FinancialValue></p></div><div className="rounded-lg bg-white p-3"><p className="text-xs text-slate-500">With this change</p><p className="mt-1 font-semibold"><FinancialValue>{scenario.scenario.projected_date||'Not reached'}</FinancialValue></p><p className="text-xs text-slate-500"><FinancialValue>{scenario.scenario.projected_months??'Over 100'} months</FinancialValue></p></div></div>
        <p className="mt-3 text-xs text-slate-600"><FinancialValue>Observed {scenario.category.name} average: {money(scenario.history.average_monthly_spending)}/month over {scenario.history.history_months} completed months ({scenario.history.history_start}–{scenario.history.history_end}, {scenario.history.transaction_count} categorized outflows).</FinancialValue></p>
        <p className="mt-1 text-xs text-slate-600"><FinancialValue>Planned reduction: {money(scenario.scenario.monthly_reduction)}/month for {scenario.scenario.duration_months} months ({money(scenario.scenario.planned_total_reduction)} total). Applied to goal in projection: {money(scenario.scenario.additional_goal_funding_applied)}.</FinancialValue></p>
        {scenario.goal.configured_target_date&&<p className="mt-1 text-xs text-slate-600"><FinancialValue>Configured target date: {scenario.goal.configured_target_date}.</FinancialValue></p>}
        {scenario.warnings.length>0&&<ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-800">{scenario.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul>}
        <details className="mt-3 rounded-lg bg-white p-3"><summary className="cursor-pointer text-xs font-semibold text-navy">Assumptions and calculation details</summary><p className="mt-2 text-xs text-slate-500"><FinancialValue>Baseline monthly savings estimate: {money(scenario.baseline.monthly_savings_estimate)}. One-time sweep estimate: {money(scenario.baseline.one_time_sweep_estimate)}.</FinancialValue></p><ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-600">{scenario.assumptions.map((assumption,index)=><li key={index}><FinancialValue>{assumption}</FinancialValue></li>)}</ul></details>
      </div>}

      {mode==='scenario'&&<form onSubmit={(event)=>void submitScenario(event)} className="space-y-3 border-t p-4">
        {optionsLoading&&<p className="text-xs text-slate-500">Loading your categories and goals…</p>}
        {optionsError&&<p className="rounded bg-rose-50 p-2 text-xs text-rose-800" role="alert">Could not load your PFOS categories and goals. Please try again.</p>}
        {!optionsLoading&&options&&<>
          <label className="block text-xs font-medium text-slate-700">Expense category<select aria-label="Expense category" className="mt-1 w-full rounded-lg border border-slate-300 bg-white p-2 text-sm" value={categoryId} onChange={(event)=>setCategoryId(event.target.value)}><option value="">Choose a category</option>{options.categories.map((category)=><option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
          <label className="block text-xs font-medium text-slate-700">Savings goal<select aria-label="Savings goal" className="mt-1 w-full rounded-lg border border-slate-300 bg-white p-2 text-sm" value={goalId} onChange={(event)=>setGoalId(event.target.value)}><option value="">Choose a goal</option>{options.goals.map((goal)=><option key={goal.id} value={goal.id}>{goal.name} · <FinancialOptionValue>{money(goal.target_amount)}</FinancialOptionValue></option>)}</select></label>
          {options.categories.length===0&&<p className="text-xs text-amber-800">No expense categories are available yet. Add one in Category Tracker first.</p>}
          {options.goals.length===0&&<p className="text-xs text-amber-800">Create a savings goal in Goals before calculating a goal timeline.</p>}
          <div className="grid grid-cols-2 gap-3"><label className="block text-xs font-medium text-slate-700">Reduce by per month<input aria-label="Monthly spending reduction" className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm" type="number" min="0.01" max="100000" step="0.01" inputMode="decimal" value={reduction} onChange={(event)=>setReduction(event.target.value)} placeholder="$150" required/></label><label className="block text-xs font-medium text-slate-700">For how long<select aria-label="Scenario duration" className="mt-1 w-full rounded-lg border border-slate-300 bg-white p-2 text-sm" value={duration} onChange={(event)=>setDuration(event.target.value)}>{[3,6,12,18,24,36,60,120].map((monthCount)=><option key={monthCount} value={monthCount}>{monthCount} months</option>)}</select></label></div>
          <label className="block text-xs font-medium text-slate-700">Category history window<select aria-label="Category history window" className="mt-1 w-full rounded-lg border border-slate-300 bg-white p-2 text-sm" value={historyMonths} onChange={(event)=>setHistoryMonths(event.target.value)}>{[3,6,12,24].map((monthCount)=><option key={monthCount} value={monthCount}>{monthCount} completed months</option>)}</select></label>
        </>}
        <button type="submit" disabled={loading||!categoryId||!goalId||!reduction||!options?.categories.length||!options.goals.length} className="flex w-full items-center justify-center gap-2 rounded-lg bg-navy px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"><Calculator size={16}/> Calculate scenario</button>
      </form>}

      <div className="border-t p-3">
        <div className="mb-2 flex flex-wrap gap-2">{mode==='help'?suggestions.map((topic)=><button key={topic.id} type="button" onClick={()=>useSuggestedQuestion(topic.title)} className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-left text-[11px] text-slate-700 hover:border-navy hover:text-navy">{topic.title}</button>):<button type="button" onClick={()=>useSuggestedQuestion('How much am I spending on shopping?')} className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-700 hover:border-navy hover:text-navy">Summarize a category</button>}</div>
        <form onSubmit={submitQuestion} className="flex items-center gap-2"><input ref={inputRef} aria-label="Ask PFOS Assistant" className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-navy focus:ring-2 focus:ring-navy/10" value={question} onChange={(event)=>setQuestion(event.target.value)} placeholder="Ask about PFOS or spending…" maxLength={500}/><button type="submit" disabled={!question.trim()||loading} aria-label="Send question" className="rounded-xl bg-navy p-2.5 text-white disabled:opacity-40"><Send size={17}/></button></form>
      </div>
    </section>}
    <button ref={triggerRef} type="button" aria-label={open?'Close PFOS Assistant':'Open PFOS Assistant'} aria-expanded={open} onClick={()=>setOpen((current)=>!current)} className="flex items-center gap-2 rounded-full bg-navy px-4 py-3 text-sm font-semibold text-white shadow-lg ring-1 ring-white/20 transition hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-navy"><MessageCircle size={19}/><span className="hidden sm:inline">Ask PFOS</span></button>
  </div>;
}
