import '../../../web-react/node_modules/fake-indexeddb/auto/index.mjs';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { clearOffline, readOffline, saveSnapshot, setQueue, type Snapshot } from '../../../web-react/src/features/offline/storage';
import { refreshOffline, syncMemos, cancelOfflineSync } from '../../../web-react/src/features/offline/sync';

const snapshot = (user = 'alice'): Snapshot => ({
  scope: { user_id: user, household_id: 'home', member_id: user }, revision: 'r1', synced_at: new Date().toISOString(), ttl_seconds: 86400,
  data: { tasks: [{ id: 'task', title: 'memo', version: 1 }], sessions: [], documents: [] },
});
beforeEach(async () => { sessionStorage.clear(); cancelOfflineSync(); await clearOffline(); });
afterEach(() => { vi.restoreAllMocks(); });

it('requires per-session permission and isolates account/household changes', async () => {
  await saveSnapshot(snapshot());
  await setQueue([{ title: 'only alice', request_id: 'a' }]);
  expect((await readOffline()).queue).toHaveLength(1);
  sessionStorage.clear();
  expect((await readOffline()).snapshot).toBeUndefined();
  await saveSnapshot(snapshot('bob'));
  expect((await readOffline()).queue).toEqual([]);
  expect((await readOffline()).snapshot?.scope.user_id).toBe('bob');
  await clearOffline();
  expect((await readOffline()).snapshot).toBeUndefined();
});

it('expires metadata while retaining explicitly saved unsynced edits', async () => {
  await saveSnapshot({ ...snapshot(), synced_at: new Date(Date.now() - 86401000).toISOString() });
  await setQueue([{ title: 'keep draft', request_id: 'a' }]);
  expect((await readOffline()).snapshot).toBeUndefined();
  expect((await readOffline()).queue[0].title).toBe('keep draft');
});

it('caps quota and queue and cannot resurrect data after a concurrent logout', async () => {
  const saving = saveSnapshot(snapshot());
  await clearOffline(); await saving;
  expect((await readOffline()).snapshot).toBeUndefined();
  await saveSnapshot(snapshot());
  await expect(setQueue(Array.from({ length: 51 }, (_, index) => ({ title: 'x', request_id: String(index) })))).rejects.toThrow('50');
  await expect(saveSnapshot({ ...snapshot(), data: { ...snapshot().data, documents: [{ id: 'large', title: 'x'.repeat(1024 * 1024) }] } })).rejects.toThrow('1MB');
});

it('invalidates revoked permissions and blocks late synchronization results', async () => {
  await saveSnapshot(snapshot());
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: 'forbidden' }), { status: 403 }));
  await expect(refreshOffline()).rejects.toThrow();
  expect((await readOffline()).snapshot).toBeUndefined();
  await saveSnapshot(snapshot());
  let reply!: (response: Response) => void;
  fetcher.mockImplementation(() => new Promise(resolve => { reply = resolve; }));
  const refresh = refreshOffline();
  await vi.waitFor(() => expect(reply).toBeTypeOf('function'));
  cancelOfflineSync(); await clearOffline();
  reply(new Response(JSON.stringify(snapshot())));
  await refresh;
  expect((await readOffline()).snapshot).toBeUndefined();
});

it('coalesces replays, preserves conflicts, and reuses the same request id', async () => {
  await saveSnapshot(snapshot());
  await setQueue([{ title: 'mine', request_id: 'one', task_id: 'task', expected_version: 1 }]);
  const calls: string[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
    if (String(url).endsWith('/snapshot')) return new Response(JSON.stringify(snapshot()));
    calls.push(String(options?.body));
    return new Response(JSON.stringify({ error: 'version_conflict' }), { status: 409 });
  });
  await Promise.all([syncMemos(), syncMemos()]);
  expect(calls).toHaveLength(1);
  expect(JSON.parse(calls[0]).request_id).toBe('one');
  expect(JSON.parse(calls[0]).scope.user_id).toBe('alice');
  const local = await readOffline();
  expect(local.queue[0]).toMatchObject({ title: 'mine', error: 'conflict', expected_version: 1 });
  await syncMemos();
  expect(calls).toHaveLength(1); // Never silently overwrite a conflict.
});

it('clears other tabs through storage events even without BroadcastChannel', async () => {
  const { initializeOfflinePrivacy } = await import('../../../web-react/src/features/offline/storage');
  const cleanup = initializeOfflinePrivacy();
  await saveSnapshot(snapshot());
  window.dispatchEvent(new StorageEvent('storage', { key: 'claw-offline-revoke',
    newValue: JSON.stringify({ type: 'clear', signOut: false, id: 'cross-tab-example' }) }));
  await vi.waitFor(async () => expect((await readOffline()).snapshot).toBeUndefined());
  cleanup();
});

it('retains concurrent memo additions without replacing another tab edits', async () => {
  await saveSnapshot(snapshot());
  await Promise.all([
    setQueue(current => [...current, { request_id: 'a', title: 'first' }]),
    setQueue(current => [...current, { request_id: 'b', title: 'second' }]),
  ]);
  expect((await readOffline()).queue.map(row => row.request_id)).toEqual(['a', 'b']);
});
