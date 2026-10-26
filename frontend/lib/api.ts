export function apiBase() {
  const desktop = typeof window !== 'undefined'
    ? (window as Window & { pfosDesktop?: { apiBase: string } }).pfosDesktop : undefined;
  return desktop?.apiBase || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
}
import { expireSession } from './auth-session';

export async function api(path: string, init: RequestInit = {}) {
  const token = typeof window !== 'undefined' ? localStorage.getItem('pfos_token') : null;
  const view = typeof window !== 'undefined' ? localStorage.getItem('pfos_view_user_id') : null;
  const viewScopedPaths = [
    '/dashboard', '/transactions', '/available-cash-planner', '/planner-carryovers',
    '/planner-adjustments', '/planner-income-allocations', '/planner-income-rules',
    '/classification-rules', '/classification-suggestions', '/category-tracker', '/reports',
  ];
  if (view && !path.includes('view_user_id=') && !path.includes('view_scope=joint')
    && viewScopedPaths.some((prefix) => path.startsWith(prefix))) {
    path += `${path.includes('?') ? '&' : '?'}view_user_id=${view}`;
  }

  const response = await fetch(apiBase() + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const isLoginRequest = path.startsWith('/auth/login') || path.startsWith('/auth/register');
    if (response.status === 401 && token && !isLoginRequest) expireSession(token);
    throw new Error((await response.json().catch(() => ({ detail: 'Request failed' }))).detail);
  }
  return response.status === 204 ? null : response.json();
}
export const money=(n:number|string)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(n));
