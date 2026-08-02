export function activeViewKey() {
  if (typeof window === 'undefined') return 'joint';
  return localStorage.getItem('pfos_view_user_id') || 'joint';
}

export function loadViewState<T>(page: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const value=localStorage.getItem(`pfos.view.${page}.${activeViewKey()}`);
    return value ? { ...fallback, ...JSON.parse(value) } : fallback;
  } catch { return fallback; }
}

export function saveViewState(page: string, value: unknown) {
  if (typeof window !== 'undefined') localStorage.setItem(`pfos.view.${page}.${activeViewKey()}`,JSON.stringify(value));
}
