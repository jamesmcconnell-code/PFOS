'use client';
import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { expireSession, SESSION_EXPIRED_EVENT, tokenExpirationTime } from '@/lib/auth-session';

export function Protected({ children }: { children: React.ReactNode }) {
  const [ok, setOk] = useState(false);
  const router = useRouter();

  const promptSignIn = useCallback(() => {
    setOk(false);
    router.replace('/login');
  }, [router]);

  useEffect(() => {
    const token = localStorage.getItem('pfos_token');
    if (!token) {
      promptSignIn();
      return;
    }

    const expiration = tokenExpirationTime(token);
    if (expiration === null || expiration <= Date.now()) {
      expireSession(token);
      promptSignIn();
      return;
    }

    const timeout = window.setTimeout(() => {
      if (expireSession(token)) promptSignIn();
    }, expiration - Date.now());

    const checkExpiration = () => {
      if (Date.now() >= expiration && expireSession(token)) promptSignIn();
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, promptSignIn);
    window.addEventListener('focus', checkExpiration);
    document.addEventListener('visibilitychange', checkExpiration);
    setOk(true);

    return () => {
      window.clearTimeout(timeout);
      window.removeEventListener(SESSION_EXPIRED_EVENT, promptSignIn);
      window.removeEventListener('focus', checkExpiration);
      document.removeEventListener('visibilitychange', checkExpiration);
    };
  }, [promptSignIn]);

  return ok ? <>{children}</> : <p className="p-8 text-slate-500">Loading your finances…</p>;
}
