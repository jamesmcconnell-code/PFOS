'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/** Keeps bookmarked /settings links working while Settings lives in the global drawer. */
export default function SettingsPage() {
  const router = useRouter();
  useEffect(() => {
    window.dispatchEvent(new Event('pfos-open-settings'));
    router.replace('/dashboard');
  }, [router]);
  return <p className="p-8 text-slate-500">Opening settings…</p>;
}
