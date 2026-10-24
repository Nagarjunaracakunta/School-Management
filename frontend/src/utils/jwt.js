// Decodes the JWT payload for DISPLAY and menu purposes only (name, role, expiry).
// The browser cannot verify the signature, so this is never a security decision:
// every backend service re-verifies the token and checks the role itself.
export function decodeJwt(token) {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(payload).split('').map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0')).join(''),
    );
    return JSON.parse(json);
  } catch {
    return null;
  }
}

export function isExpired(claims, nowMs = Date.now()) {
  return !claims || typeof claims.exp !== 'number' || claims.exp * 1000 <= nowMs;
}
