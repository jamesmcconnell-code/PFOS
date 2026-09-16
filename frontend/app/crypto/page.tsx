'use client';
import { FinancialValue } from "@/components/financial-value";

import { useEffect, useState } from 'react';
import { api, money } from '@/lib/api';
import { Protected } from '@/components/protected';

export default function Crypto() {
  const [assets, setAssets] = useState<any[]>([]);
  useEffect(() => {
    const load = () => api('/dashboard').then((dashboard) => setAssets(dashboard.crypto_assets || [])).catch(() => setAssets([]));
    load();
    window.addEventListener('pfos-view-change', load);
    return () => window.removeEventListener('pfos-view-change', load);
  }, []);
  return <Protected><h1 className="text-3xl font-bold">Crypto assets</h1><p className="mt-1 text-slate-500">Current quantity and refreshed USD value across linked crypto sources.</p><div className="card mt-6 max-w-2xl overflow-hidden p-0"><table className="w-full text-left"><thead className="border-b text-sm text-slate-500"><tr><th className="p-4">Asset</th><th className="p-4 text-right">Quantity</th><th className="p-4 text-right">USD value</th></tr></thead><tbody>{assets.map((asset) => <tr key={asset.symbol} className="border-b last:border-0"><td className="p-4 font-medium">{asset.symbol}</td><td className="p-4 text-right"><FinancialValue>{Number(asset.quantity).toLocaleString(undefined,{maximumFractionDigits:8})}</FinancialValue> {asset.symbol}</td><td className="p-4 text-right"><FinancialValue>{asset.quote_available ? money(asset.usd_value) : 'Quote unavailable'}</FinancialValue></td></tr>)}{!assets.length && <tr><td className="p-4 text-slate-500" colSpan={3}>No crypto assets available.</td></tr>}</tbody></table></div></Protected>;
}
