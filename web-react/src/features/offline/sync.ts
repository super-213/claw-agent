import { jsonRequest, ApiError } from '../../api/client';
import { clearOffline, readOffline, saveSnapshot, setQueue, scopeKey, type Snapshot } from './storage';
let running: Promise<void> | undefined;
let epoch = 0;
export const cancelOfflineSync = () => { epoch++; };

export async function refreshOffline(enable = false) {
  const captured = epoch;
  const current = await readOffline();
  if (!enable && !current.snapshot && !current.queue.length) return;
  try {
    const result = await jsonRequest<Omit<Snapshot, 'data'> & { data: Snapshot['data'] | null }>('/api/offline/snapshot', {
      method: 'POST', body: JSON.stringify({ revision: current.snapshot?.revision }),
    });
    if (captured !== epoch) return;
    const data = result.data || (current.snapshot && scopeKey(current.snapshot.scope) === scopeKey(result.scope) ? current.snapshot.data : undefined);
    if (!data) throw new Error('离线快照无效，请重新同步。');
    await saveSnapshot({ ...result, data });
  } catch (error) {
    if (error instanceof ApiError && [401, 403].includes(error.status)) await clearOffline();
    throw error;
  }
}

export function syncMemos(): Promise<void> {
  if (running) return running;
  const captured = epoch;
  running = (async () => {
    // Always reauthenticate and replace/revalidate permissions before replaying writes.
    await refreshOffline();
    const state = await readOffline();
    if (!state.snapshot || captured !== epoch) return;
    for (const memo of state.queue) {
      if (memo.error || captured !== epoch) continue;
      try {
        await jsonRequest('/api/offline/memos', { method: 'POST', body: JSON.stringify({ ...memo, scope: state.snapshot.scope }) });
        if (captured !== epoch) return;
        await setQueue(queue => queue.filter(row => row.request_id !== memo.request_id));
      } catch (error) {
        if (captured !== epoch) return;
        if (error instanceof ApiError && [401, 403].includes(error.status)) { await clearOffline(); throw error; }
        await setQueue(queue => queue.map(row => row.request_id === memo.request_id ? { ...row,
          error: error instanceof ApiError && error.status === 409 ? 'conflict' : 'failed' } : row));
      }
    }
    if (captured === epoch) await refreshOffline();
  })().finally(() => { running = undefined; });
  return running;
}
