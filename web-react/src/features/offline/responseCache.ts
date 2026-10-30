// Network-first cache for data already read in normal pages. Never cache credentials.
import type { User } from '../../api/types';
const OWNER = 'claw-response-cache-owner';
let generation = 0;
let pending: Promise<unknown> = Promise.resolve();
const owner = () => { try { return localStorage.getItem(OWNER); } catch { return null; } };
export const cacheContext = (expectedOwner?: string) => ({ owner: expectedOwner || owner(), generation });
type Context = ReturnType<typeof cacheContext>;
const current = (context: Context) => context.owner === owner() && context.generation === generation;

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('claw-response-cache', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('responses');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function access<T>(action: (store: IDBObjectStore) => IDBRequest<T>, write = false): Promise<T> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('responses', write ? 'readwrite' : 'readonly');
      const request = action(tx.objectStore('responses'));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally { db.close(); }
}
function enqueue(action: () => Promise<unknown>) {
  const job = pending.catch(() => undefined).then(action);
  // Storage failures must never fail an otherwise successful online request.
  pending = job.catch(() => undefined);
  return pending;
}
export function cacheableRead(url: string) {
  const path = url.split('?')[0];
  if (/^\/api\/home\/(polls|relays|board|notifications)(\/|$)/.test(path)) return false;
  return path === '/api/auth/me' || path === '/api/skills' ||
    (/^\/api\/(home|sessions|knowledge|interactive-cards)(\/|$)/.test(path) &&
      !/\/(share|assets|tasks-migration)(\/|$)/.test(path));
}
export function saveResponse(url: string, data: unknown, context: Context) {
  return enqueue(async () => {
    if (!context.owner || !current(context)) return;
    await access(store => store.put({ owner: context.owner, data }, url), true);
  });
}
export async function cachedResponse(url: string, context: Context): Promise<{ data: unknown } | undefined> {
  await pending;
  if (!context.owner || !current(context)) return;
  try {
    const row = await access(store => store.get(url));
    if (current(context) && row?.owner === context.owner) return { data: row.data };
  } catch { /* A missing/unavailable cache is an ordinary network failure. */ }
}
export function clearResponseCache() {
  generation++;
  try { localStorage.removeItem(OWNER); } catch { /* Storage may be disabled. */ }
  return enqueue(() => access(store => store.clear(), true));
}
export function bindCacheUser(user: User) {
  if (owner() !== user.id) {
    void clearResponseCache();
    try { localStorage.setItem(OWNER, user.id); } catch { /* Online use still works. */ }
  }
  return saveResponse('/api/auth/me', { user }, cacheContext());
}
export function invalidateResponseCache(url: string) {
  generation++;
  return enqueue(async () => {
    // Refresh the changed business area without discarding unrelated cached pages.
    const prefix = url.match(/^\/api\/(home|sessions|knowledge|interactive-cards)(?:\/|$)/)?.[0].replace(/\/$/, '');
    if (!prefix) return;
    const keys = await access(store => store.getAllKeys());
    for (const key of keys) {
      if (typeof key === 'string' && (key === prefix || key.startsWith(`${prefix}/`) || key.startsWith(`${prefix}?`))) {
        await access(store => store.delete(key), true);
      }
    }
  });
}
