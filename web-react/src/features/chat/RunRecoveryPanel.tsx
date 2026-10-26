import { useEffect, useState } from 'react';
import { chatApi } from '../../api/chat';
import { BottomSheet } from '../../components/ui/BottomSheet';

export function RunRecoveryPanel({ sessionId, runId, onClose, onResolved }: { sessionId: string; runId: string; onClose: () => void; onResolved: (cancelled: boolean) => void }) {
  const [call, setCall] = useState<{ id: string; name?: string; arguments?: object }>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    void chatApi.runs(sessionId).then(({ runs }) => {
      if (!live) return;
      const run = runs.find(item => item.id === runId);
      const id = Object.entries(run?.tool_ledger || {}).find(([, entry]) => entry.status === 'executing')?.[0];
      const tool = run?.steps?.flatMap(step => step.tool_calls || []).find(item => item.id === id);
      if (id) setCall({ ...tool, id });
      else setError('当前没有需要核对的操作，请返回后重新读取状态。');
    }).catch(() => { if (live) setError('无法读取操作记录，请稍后重试。'); });
    return () => { live = false; };
  }, [runId, sessionId]);
  const resolve = async (action: string) => {
    if (!call || busy || !confirm(action === 'retry' ? '重新执行可能造成重复操作。确认已经核对实际结果并允许再次执行？' : '确认按你的核对结果处理这项操作？')) return;
    setBusy(true); setError('');
    try { await chatApi.resolveTool(runId, call.id, action); onResolved(action === 'cancel'); }
    catch (caught) { setError((caught as Error).message); setBusy(false); }
  };
  return <BottomSheet title="核对中断前的操作" onClose={() => { if (!busy) onClose(); }}>
    <p>服务器未能确认这项操作的结果，已暂停执行。请先核对实际结果，再选择如何继续。</p>
    {call && <><strong>{call.name || call.id}</strong><pre className="chat-recovery-arguments">{JSON.stringify(call.arguments || {}, null, 2)}</pre>
      <button className="pwa-sheet-action" disabled={busy} onClick={() => void resolve('assume_succeeded')}>确认已成功，继续后续步骤</button>
      <button className="pwa-sheet-action" disabled={busy} onClick={() => void resolve('assume_failed')}>确认未成功，按失败结果继续</button>
      <button className="pwa-sheet-action" disabled={busy} onClick={() => void resolve('retry')}>允许重新执行这项操作</button>
      <button className="pwa-sheet-action" disabled={busy} onClick={() => void resolve('cancel')}>结束整个任务</button></>}
    {error && <p role="alert">{error}</p>}
  </BottomSheet>;
}
