import '../../../web-react/node_modules/fake-indexeddb/auto/index.mjs';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { jsonRequest } from '../../../web-react/src/api/client';
import { bindCacheUser, cacheContext, cachedResponse, clearResponseCache } from '../../../web-react/src/features/offline/responseCache';
const user = (id: string) => ({ id, username: id, display_name: id, role: 'user' as const, status: 'active' as const });
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
beforeEach(async () => { await clearResponseCache(); await bindCacheUser(user('alice')); });
afterEach(() => vi.restoreAllMocks());

it('automatically caches complete page data and restores it after an offline reload', async () => {
  const data = { id: 'chat', messages: [{ role: 'assistant', content: '完整对话正文' }] };
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(data));
  expect(await jsonRequest('/api/sessions/chat')).toEqual(data);
  fetcher.mockRejectedValue(new TypeError('Failed to fetch'));
  expect(await jsonRequest('/api/sessions/chat')).toEqual(data);
  expect(await jsonRequest('/api/auth/me')).toEqual({ user: user('alice') });
});
it('always prefers fresh network data and replaces the cached version', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ title: 'old' }));
  await jsonRequest('/api/knowledge/documents/one');
  fetcher.mockResolvedValue(json({ title: 'new' }));
  expect(await jsonRequest('/api/knowledge/documents/one')).toEqual({ title: 'new' });
  fetcher.mockRejectedValue(new TypeError('offline'));
  expect(await jsonRequest('/api/knowledge/documents/one')).toEqual({ title: 'new' });
});
it.each([401, 403])('never uses cached data for a permission failure %s', async status => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ title: 'private' }));
  await jsonRequest('/api/home/tasks');
  fetcher.mockResolvedValue(json({ error: 'denied' }, status));
  await expect(jsonRequest('/api/home/tasks')).rejects.toMatchObject({ status });
  fetcher.mockRejectedValue(new TypeError('offline'));
  await expect(jsonRequest('/api/home/tasks')).rejects.toThrow('offline');
});
it('clears account data on switching and refuses late responses after logout', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ title: 'Alice only' }));
  await jsonRequest('/api/home/tasks');
  await bindCacheUser(user('bob'));
  fetcher.mockRejectedValue(new TypeError('offline'));
  await expect(jsonRequest('/api/home/tasks')).rejects.toThrow('offline');
  let reply!: (value: Response) => void;
  fetcher.mockImplementation(() => new Promise(resolve => { reply = resolve; }));
  const request = jsonRequest('/api/home/tasks');
  await clearResponseCache();
  reply(json({ title: 'Late Bob response' })); await request;
  await bindCacheUser(user('bob'));
  expect(await cachedResponse('/api/home/tasks', cacheContext())).toBeUndefined();
});
it('invalidates related data after writes while keeping other pages cached', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async url => json({ source: String(url) }));
  await jsonRequest('/api/home/tasks'); await jsonRequest('/api/knowledge/documents');
  await jsonRequest('/api/home/tasks/one/complete', { method: 'POST', body: '{}' });
  fetcher.mockRejectedValue(new TypeError('offline'));
  await expect(jsonRequest('/api/home/tasks')).rejects.toThrow('offline');
  expect(await jsonRequest('/api/knowledge/documents')).toEqual({ source: '/api/knowledge/documents' });
});
it('does not cache security settings or turn aborted, HTTP and write failures into cached success', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ secret: 'not stored' }));
  await jsonRequest('/api/config'); await jsonRequest('/api/auth/passkeys');
  await jsonRequest('/api/home/tasks');
  fetcher.mockRejectedValue(new TypeError('offline'));
  await expect(jsonRequest('/api/config')).rejects.toThrow();
  await expect(jsonRequest('/api/auth/passkeys')).rejects.toThrow();
  await expect(jsonRequest('/api/home/tasks', { method: 'POST' })).rejects.toThrow();
  const controller = new AbortController(); controller.abort();
  await expect(jsonRequest('/api/home/tasks', { signal: controller.signal })).rejects.toThrow();
  fetcher.mockResolvedValue(json({ error: 'server error' }, 500));
  await expect(jsonRequest('/api/home/tasks')).rejects.toMatchObject({ status: 500 });
});
it('never exposes data when a tab identity differs from the shared cache owner', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ title: 'Alice only' }));
  await jsonRequest('/api/home/tasks');
  expect(await cachedResponse('/api/home/tasks', cacheContext('bob'))).toBeUndefined();
});
it('keeps online reads working when browser storage is unavailable', async () => {
  vi.spyOn(indexedDB, 'open').mockImplementation(() => { throw new Error('storage blocked'); });
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ title: 'online' }));
  expect(await jsonRequest('/api/home/tasks')).toEqual({ title: 'online' });
});

it('never persists or restores expiring family activity or board responses', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ title: '活动私密内容' }));
  for (const url of ['/api/home/polls/poll_1', '/api/home/relays/relay_1', '/api/home/board/feed']) {
    await jsonRequest(url);
    expect(await cachedResponse(url, cacheContext())).toBeUndefined();
  }
  await jsonRequest('/api/home/tasks', { cache: 'no-store' });
  expect(await cachedResponse('/api/home/tasks', cacheContext())).toBeUndefined();
  fetcher.mockRejectedValue(new TypeError('offline'));
  await expect(jsonRequest('/api/home/polls/poll_1')).rejects.toThrow('offline');
});
