import { clearResponseCache } from './responseCache';
// Explicit opt-in only. One active account/household scope per browser database.
export interface Scope { user_id: string; household_id: string; member_id: string }
export interface Metadata { id: string; title: string; version?: number; due_date?: string; space_type?: string; temporal_type?: string }
export interface Snapshot { scope: Scope; revision: string; synced_at: string; ttl_seconds: number;
  data: { tasks: Metadata[]; sessions: Metadata[]; documents: Metadata[] } }
export interface Memo { request_id: string; title: string; task_id?: string; expected_version?: number; error?: string }
interface State { snapshot?: Snapshot; queue: Memo[] }
const DATABASE = 'claw-offline';
const PERMIT = 'claw-offline-scope';
const REVOKE = 'claw-offline-revoke';
let lastNotification = '';
export const scopeKey = (scope: Scope) => JSON.stringify([scope.user_id, scope.household_id, scope.member_id]);
let generation = 0;
let serial: Promise<unknown> = Promise.resolve();
let channel: BroadcastChannel | undefined;
const empty = (): State => ({ queue: [] });
const changed = () => window.dispatchEvent(new Event('claw-offline-change'));

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    // v1 contains only a bounded metadata snapshot and low-risk memo queue.
    // Future migrations must delete unknown/sensitive records before exposing them.
    request.onupgradeneeded = () => {
      const db = request.result;
      for (const store of Array.from(db.objectStoreNames)) db.deleteObjectStore(store);
      db.createObjectStore('state');
    };
    request.onsuccess = () => { request.result.onversionchange = () => request.result.close(); resolve(request.result); };
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('请关闭本站其他窗口后重试离线存储。'));
  });
}

async function transact(update?: (current: State) => State): Promise<State> {
  const db = await open();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('state', update ? 'readwrite' : 'readonly');
      const store = tx.objectStore('state');
      const request = store.get('active');
      let result: State;
      request.onsuccess = () => {
        result = request.result || empty();
        if (update) {
          try {
            result = update(result);
            if (new Blob([JSON.stringify(result)]).size > 1024 * 1024) throw new Error('离线数据超过 1MB，请删除部分本地草稿。');
            store.put(result, 'active');
          } catch (error) { tx.abort(); reject(error); }
        }
      };
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error || new Error('离线存储已取消'));
    });
  } finally { db.close(); }
}

export async function readOffline(): Promise<State> {
  const state = await transact();
  const permit = sessionStorage.getItem(PERMIT);
  if (!state.snapshot || permit !== scopeKey(state.snapshot.scope)) return empty();
  if (Date.now() - Date.parse(state.snapshot.synced_at) > state.snapshot.ttl_seconds * 1000) return { queue: state.queue };
  return state;
}

export function clearOffline(broadcast = true, signOut = false): Promise<void> {
  generation++;
  const cacheCleared = clearResponseCache();
  window.dispatchEvent(new Event('claw-offline-cleared'));
  try { sessionStorage.removeItem(PERMIT); } catch { /* Still purge IndexedDB when session storage is blocked. */ }
  if (broadcast) {
    const notice = { type: 'clear', signOut, id: window.crypto.randomUUID() };
    channel?.postMessage(notice);
    try { localStorage.setItem(REVOKE, JSON.stringify(notice)); } catch { /* BroadcastChannel remains available where storage is blocked. */ }
  }
  changed();
  const job = serial.catch(() => undefined).then(async () => { await transact(() => empty()); await cacheCleared; changed(); });
  serial = job;
  return job;
}

export function saveSnapshot(snapshot: Snapshot): Promise<void> {
  const captured = generation;
  const job = serial.catch(() => undefined).then(async () => {
    if (captured !== generation) return;
    await transact(current => ({ snapshot, queue: current.snapshot && scopeKey(current.snapshot.scope) === scopeKey(snapshot.scope) ? current.queue : [] }));
    if (captured !== generation) return;
    sessionStorage.setItem(PERMIT, scopeKey(snapshot.scope));
    changed();
  });
  serial = job;
  return job;
}

export function setQueue(queue: Memo[] | ((current: Memo[]) => Memo[])): Promise<void> {
  if (Array.isArray(queue) && queue.length > 50) return Promise.reject(new Error('最多保留 50 条待同步备忘。'));
  const captured = generation;
  const permit = sessionStorage.getItem(PERMIT);
  const job = serial.catch(() => undefined).then(async () => {
    if (captured !== generation) return;
    await transact(current => {
      if (!current.snapshot || permit !== scopeKey(current.snapshot.scope)) throw new Error('请先联网验证账号并启用离线查看。');
      const next = typeof queue === 'function' ? queue(current.queue) : queue;
      if (next.length > 50) throw new Error('最多保留 50 条待同步备忘。');
      return { ...current, queue: next };
    });
    changed();
  });
  serial = job;
  return job;
}

export function initializeOfflinePrivacy() {
  const receive = (notice: { type?: string; id?: string; signOut?: boolean }) => {
    if (notice.type !== 'clear' || !notice.id || notice.id === lastNotification) return;
    lastNotification = notice.id;
    void clearOffline(false).catch(() => undefined);
    if (notice.signOut) window.dispatchEvent(new Event('claw-auth-cleared'));
  };
  const storage = (event: StorageEvent) => {
    if (event.key !== REVOKE || !event.newValue) return;
    try { receive(JSON.parse(event.newValue)); } catch { /* Ignore unrelated/corrupt storage markers. */ }
  };
  if ('BroadcastChannel' in window) {
    channel = new BroadcastChannel('claw-offline-privacy');
    channel.onmessage = (event) => receive(event.data || {});
  }
  const unauthorized = () => { void clearOffline().catch(() => undefined); };
  window.addEventListener('storage', storage);
  window.addEventListener('claw-api-unauthorized', unauthorized);
  return () => {
    channel?.close(); channel = undefined;
    window.removeEventListener('storage', storage);
    window.removeEventListener('claw-api-unauthorized', unauthorized);
  };
}
