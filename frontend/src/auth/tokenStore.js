// sessionStorage: cleared when the tab closes and not shared across tabs.
// Trade-off: any XSS could read it. The stronger production option is an httpOnly,
// Secure, SameSite cookie set by the Auth Service. Storage can throw (private mode), so wrap it.
const KEY = 'school.access_token';

export const tokenStore = {
  get() {
    try { return sessionStorage.getItem(KEY); } catch { return null; }
  },
  set(token) {
    try { sessionStorage.setItem(KEY, token); } catch { /* keep working in memory only */ }
  },
  clear() {
    try { sessionStorage.removeItem(KEY); } catch { /* ignore */ }
  },
};
