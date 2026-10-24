import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { authApi } from '../api/services.js';
import { setUnauthorizedHandler } from '../api/client.js';
import { decodeJwt, isExpired } from '../utils/jwt.js';
import { tokenStore } from './tokenStore.js';

const AuthContext = createContext(null);

function userFromToken(token) {
  const claims = token ? decodeJwt(token) : null;
  if (isExpired(claims)) return null;
  return { id: claims.sub, name: claims.name ?? claims.email ?? claims.sub, role: claims.role };
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => userFromToken(tokenStore.get()));

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  const login = useCallback(async (email, password) => {
    const { access_token: token } = await authApi.login(email, password);
    const next = userFromToken(token);
    if (!next) throw new Error('Received an invalid or expired token');
    tokenStore.set(token);
    setUser(next);
  }, []);

  // Any 401 from any service means the session is over.
  useEffect(() => { setUnauthorizedHandler(logout); }, [logout]);

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
