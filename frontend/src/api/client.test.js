import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const store = {};
vi.stubGlobal('sessionStorage', {
  getItem: (k) => store[k] ?? null,
  setItem: (k, v) => { store[k] = v; },
  removeItem: (k) => { delete store[k]; },
});

const { request, ApiError, setUnauthorizedHandler } = await import('./client.js');
const { tokenStore } = await import('../auth/tokenStore.js');

const jsonResponse = (status, body, headers = {}) =>
  new Response(body === null ? null : JSON.stringify(body), { status, headers });

describe('api client', () => {
  beforeEach(() => { tokenStore.clear(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it('sends request id and bearer token and skips empty query params', async () => {
    tokenStore.set('abc');
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { items: [] }));
    vi.stubGlobal('fetch', fetchMock);
    await request('/students', { params: { page: 1, status: '' } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/students?page=1');
    expect(init.headers.Authorization).toBe('Bearer abc');
    expect(init.headers['X-Request-ID']).toBeTruthy();
  });

  it('maps the backend error format to ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      jsonResponse(422, { error: { code: 'validation_error', message: 'Bad input', request_id: 'r-1' } }),
    ));
    await expect(request('/admissions', { method: 'POST', body: {} })).rejects.toMatchObject({
      status: 422, code: 'validation_error', requestId: 'r-1',
    });
  });

  it('calls the unauthorized handler on 401', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: 'expired' } })));
    await expect(request('/students')).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledOnce();
  });

  it('turns a network failure into a friendly status-0 error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(request('/students')).rejects.toMatchObject({ status: 0 });
  });
});
