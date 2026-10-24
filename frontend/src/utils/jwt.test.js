import { describe, expect, it } from 'vitest';
import { decodeJwt, isExpired } from './jwt.js';

const makeToken = (claims) =>
  `h.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.s`;

describe('jwt helpers', () => {
  it('decodes claims', () => {
    expect(decodeJwt(makeToken({ sub: '1', role: 'admin' }))).toMatchObject({ role: 'admin' });
  });
  it('returns null for garbage', () => {
    expect(decodeJwt('not-a-token')).toBeNull();
  });
  it('detects expiry', () => {
    expect(isExpired({ exp: 1 })).toBe(true);
    expect(isExpired({ exp: Math.floor(Date.now() / 1000) + 600 })).toBe(false);
    expect(isExpired(null)).toBe(true);
  });
});
