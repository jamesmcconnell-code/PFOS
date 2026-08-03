'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { LayoutDashboard, WalletCards, ReceiptText, Target, ChartNoAxesCombined, Upload, Plug, Coins, HandCoins, Tags, ChartPie } from 'lucide-react';

const links = [['/dashboard','Dashboard',LayoutDashboard],['/reports','Reports',ChartPie],['/available-cash','Available cash',HandCoins],['/accounts','Accounts',WalletCards],['/transactions','Transactions',ReceiptText],['/category-tracker','Category tracker',Tags],['/import','CSV Import',Upload],['/connections','Connected Sources',Plug],['/crypto','Crypto assets',Coins],['/goals','Goals',Target],['/forecasting','Forecasting',ChartNoAxesCombined]] as const;

export function Nav() {
  const path = usePathname(), router = useRouter();
  const [members, setMembers] = useState<any[]>([]), [view, setView] = useState('');
  const supportsScopedView = path === '/dashboard' || path === '/reports' || path === '/transactions' || path === '/crypto' || path === '/available-cash' || path === '/category-tracker';

  useEffect(() => {
    setView(localStorage.getItem('pfos_view_user_id') || '');
    fetch((process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1') + '/household/members', { headers: { Authorization: `Bearer ${localStorage.getItem('pfos_token')}` } })
      .then((response) => response.json()).then(setMembers).catch(() => {});
  }, [path]);

  function changeView(value: string) {
    setView(value);
    value ? localStorage.setItem('pfos_view_user_id', value) : localStorage.removeItem('pfos_view_user_id');
    window.dispatchEvent(new Event('pfos-view-change'));
    router.refresh();
  }

  return <aside className="border-r border-slate-800 bg-navy text-slate-300 md:fixed md:inset-y-0 md:left-0 md:z-30 md:w-60 md:overflow-y-auto"><div className="p-5 text-lg font-bold text-white">PF<span className="text-mint">OS</span><p className="mt-1 text-xs font-normal text-slate-400">Personal financial operating system</p>
    {supportsScopedView && members.length > 1 && <select aria-label="Financial view" className="mt-3 w-full rounded bg-white/10 p-2 text-xs" value={view} onChange={(event) => changeView(event.target.value)}><option value="">Joint / household</option>{members.map((member) => <option value={member.id} key={member.id}>{member.display_name}</option>)}</select>}
  </div><nav className="flex overflow-x-auto px-3 pb-3 md:block">{links.map(([href,label,Icon]) => <Link key={href} href={href} className={`flex shrink-0 items-center gap-3 rounded-xl px-3 py-3 text-sm ${path===href?'bg-white/10 text-white':'hover:bg-white/5'}`}><Icon size={18}/>{label}</Link>)}</nav><button onClick={() => { localStorage.removeItem('pfos_token'); localStorage.removeItem('pfos_view_user_id'); router.push('/login'); }} className="mx-6 hidden text-xs text-slate-400 hover:text-white md:block">Log out</button></aside>;
}
