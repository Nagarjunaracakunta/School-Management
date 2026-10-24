import { tokenStore } from '../auth/tokenStore.js';

// Same-origin by default: CloudFront forwards /api/* to the ALB, so no CORS is needed.
export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export class ApiError extends Error {
  constructor(status, message, { code, requestId, details } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId; // quote this to the on-call engineer; it matches the backend logs
    this.details = details;
  }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

const newRequestId = () =>
  (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`);

function buildQuery(params) {
  const qs = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  });
  const s = qs.toString();
  return s ? `?${s}` : '';
}

// Expected error body from every service: { "error": { "code", "message", "request_id", "details" } }
export async function request(path, { method = 'GET', body, params, signal, headers = {} } = {}) {
  const requestId = newRequestId();
  const token = tokenStore.get();
  let response;
  try {
    response = await fetch(`${API_BASE}${path}${buildQuery(params)}`, {
      method,
      signal,
      headers: {
        Accept: 'application/json',
        'X-Request-ID': requestId,
        ...(body !== undefined && { 'Content-Type': 'application/json' }),
        ...(token && { Authorization: `Bearer ${token}` }),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new ApiError(0, 'Cannot reach the server. Check your connection and try again.', { requestId });
  }

  const serverRequestId = response.headers.get('X-Request-ID') ?? requestId;
  if (response.status === 204) return null;

  const payload = await response.json().catch(() => null);
  if (response.ok) return payload;

  if (response.status === 401) onUnauthorized();
  const err = payload?.error ?? {};
  throw new ApiError(response.status, err.message ?? `Request failed (${response.status})`, {
    code: err.code,
    requestId: err.request_id ?? serverRequestId,
    details: err.details,
  });
}

export const api = {
  get: (path, params, opts) => request(path, { ...opts, params }),
  post: (path, body, opts) => request(path, { ...opts, method: 'POST', body }),
  put: (path, body, opts) => request(path, { ...opts, method: 'PUT', body }),
  del: (path, opts) => request(path, { ...opts, method: 'DELETE' }),
};
