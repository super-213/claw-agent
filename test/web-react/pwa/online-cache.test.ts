import { afterEach, expect, it, vi } from 'vitest';
import { jsonRequest, uploadForm } from '../../../web-react/src/api/client';
import { invalidateResponseCache } from '../../../web-react/src/features/offline/responseCache';
vi.mock('../../../web-react/src/features/offline/responseCache', () => ({
  cacheableRead: () => true, cacheContext: () => ({}), cachedResponse: vi.fn(),
  invalidateResponseCache: vi.fn(() => new Promise(() => {})),
  saveResponse: vi.fn(() => new Promise(() => {})), clearResponseCache: vi.fn(() => new Promise(() => {})),
}));
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });
async function promptly<T>(promise: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  try { return await Promise.race([promise, new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Online response blocked by offline cache')), 100); })]); }
  finally { clearTimeout(timer!); }
}
it('returns an uploaded asset after HTTP 201 even if IndexedDB maintenance never finishes', async () => {
  class XHR {
    status = 201; responseText = JSON.stringify({ asset_id: 'asset_saved' }); upload = {}; timeout = 0;
    onload?: () => void; open() {} setRequestHeader() {} abort() {}
    send() { queueMicrotask(() => this.onload?.()); }
  }
  vi.stubGlobal('XMLHttpRequest', XHR);
  expect(await promptly(uploadForm('/api/home/board/assets', new FormData()))).toEqual({ asset_id: 'asset_saved' });
  expect(invalidateResponseCache).toHaveBeenCalledWith('/api/home/board/assets');
});
it('returns online writes and reads without waiting for cache writes', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response(JSON.stringify({ ok: true }))));
  expect(await promptly(jsonRequest('/api/home/board/posts', { method: 'POST' }))).toEqual({ ok: true });
  expect(await promptly(jsonRequest('/api/home/inventory/fridge'))).toEqual({ ok: true });
});
it('reports expired authentication immediately even when cache clearing stalls', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401 })));
  const unauthorized = vi.fn(); window.addEventListener('claw-api-unauthorized', unauthorized);
  try { await expect(promptly(jsonRequest('/api/test'))).rejects.toMatchObject({ status: 401 }); expect(unauthorized).toHaveBeenCalledOnce(); }
  finally { window.removeEventListener('claw-api-unauthorized', unauthorized); }
});
