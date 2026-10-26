export const SESSION_EXPIRED_EVENT = 'pfos-session-expired';

export function tokenExpirationTime(token: string): number | null {
  try {
    const payload = token.split('.')[1];
    if (!payload) return null;
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const claims = JSON.parse(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')));
    return typeof claims.exp === 'number' ? claims.exp * 1000 : null;
  } catch {
    return null;
  }
}

export function expireSession(expectedToken?: string): boolean {
  if (typeof window === 'undefined') return false;
  const token = localStorage.getItem('pfos_token');
  if (!token || (expectedToken && token !== expectedToken)) return false;

  localStorage.removeItem('pfos_token');
  localStorage.removeItem('pfos_view_user_id');
  sessionStorage.setItem('pfos_session_expired', '1');
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  return true;
}
