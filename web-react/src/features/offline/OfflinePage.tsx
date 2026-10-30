import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useOnline } from '../pwa/useOnline';
import { clearOffline, readOffline, setQueue, type Snapshot, type Memo, type Metadata } from './storage';
import { cancelOfflineSync, refreshOffline, syncMemos } from './sync';
import { tasksApi } from '../../api/tasks';

export function OfflinePage() {
  const online = useOnline();
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [queue, updateQueue] = useState<Memo[]>([]);
  const [title, setTitle] = useState('');
  const [editing, setEditing] = useState<Metadata>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [verified, setVerified] = useState(false);
  const [resolution, setResolution] = useState<{ memo: Memo; current: string; version: number }>();
  const load = async () => { const state = await readOffline(); setSnapshot(state.snapshot); updateQueue(state.queue); };
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : '操作失败'); }
    finally { setBusy(false); await load().catch(() => undefined); }
  };
  useEffect(() => {
    let live = true;
    setVerified(false);
    const clear = () => { setSnapshot(undefined); updateQueue([]); setTitle(''); setEditing(undefined); setResolution(undefined); };
    window.addEventListener('claw-offline-cleared', clear);
    const update = () => { if (live) void load().catch(e => setError(e.message)); };
    window.addEventListener('claw-offline-change', update);
    if (online) {
      void refreshOffline().then(() => { if (live) { setVerified(true); update(); } }).catch(e => { if (live) setError(e.message); });
    } else update();
    return () => { live = false; window.removeEventListener('claw-offline-change', update); window.removeEventListener('claw-offline-cleared', clear); };
  }, [online]);
  const visible = !online || verified;
  const add = () => run(async () => {
    if (!title.trim()) throw new Error('请输入备忘内容。');
    await setQueue(current => [...current, { request_id: crypto.randomUUID(), title: title.trim(),
      ...(editing ? { task_id: editing.id, expected_version: editing.version } : {}) }]);
    setTitle(''); setEditing(undefined);
  });
  return <main className="auth-shell"><section className="auth-panel offline-panel">
    <Link to="/home/more">← 返回更多</Link><h1>离线随身页</h1>
    <p role="status">{online ? '已联网' : '当前离线'} · 仅查看最近一次授权同步的数据</p>
    <p>主动启用后，此浏览器保存事项标题、近期对话标题和资料元数据，最长 24 小时。正文与附件不缓存。共用设备请谨慎启用；退出或切换账号会清空。</p>
    <p>离线数据仅供参考，可能已过期。恢复网络后先验证当前权限，再显示缓存。关闭本次浏览器会话后需联网重新启用。</p>
    <div className="row-actions"><button disabled={!online || busy} onClick={() => void run(async () => { await refreshOffline(true); setVerified(true); })}>启用／同步离线查看</button>
      <button disabled={busy} onClick={() => void run(async () => { cancelOfflineSync(); await clearOffline(); })}>清除此设备离线数据</button></div>
    {error && <p role="alert">{error}</p>}
    {visible && snapshot && <>
      <p>最后同步：{new Date(snapshot.synced_at).toLocaleString()} · 有效期 24 小时</p>
      {(['tasks', 'sessions', 'documents'] as const).map(kind => <section key={kind} aria-label={kind}>
        <h2>{{ tasks: '家庭与个人事项', sessions: '近期会话标题', documents: '资料元数据' }[kind]}</h2>
        <ul>{snapshot.data[kind].map(item => <li key={item.id}>{item.title}{item.due_date && ` · ${item.due_date}`}
          {kind === 'tasks' && item.space_type === 'personal' && item.temporal_type === 'undated' && <button onClick={() => { setTitle(item.title); setEditing(item); }}>编辑个人备忘</button>}</li>)}</ul>
      </section>)}
      <form onSubmit={event => { event.preventDefault(); void add(); }}>
        <h2>{editing ? '修改个人备忘' : '新增个人备忘'}</h2><p>此处输入的内容会留在设备上，点击同步后才提交。离线期间不能执行 Agent 工具。</p>
        <label>备忘内容<input maxLength={500} value={title} onChange={event => setTitle(event.target.value)} /></label>
        <button disabled={busy || !title.trim()}>保存到本地待同步队列</button>
        {editing && <button type="button" onClick={() => { setEditing(undefined); setTitle(''); }}>取消编辑</button>}
      </form>
    </>}
    {visible && !!queue.length && <section><h2>待同步备忘（{queue.length}）</h2>
      <button disabled={!online || busy} onClick={() => void run(syncMemos)}>验证权限并同步</button>
      <ul>{queue.map(memo => <li key={memo.request_id}><strong>{memo.title}</strong> · {memo.error === 'conflict' ? '版本冲突，本地修改已保留' : memo.error ? '同步失败，等待人工重试' : '等待同步'}
        <button disabled={busy} onClick={() => void run(() => setQueue(current => current.filter(row => row.request_id !== memo.request_id)))}>删除本地草稿／取消重试</button>
        {memo.error === 'failed' && <button disabled={!online || busy} onClick={() => void run(() => setQueue(current => current.map(row => row.request_id === memo.request_id ? { ...row, error: undefined } : row)))}>允许重试</button>}
        {memo.error === 'conflict' && memo.task_id && <button disabled={!online || busy} onClick={() => void run(async () => {
          const current = (await tasksApi.get(memo.task_id!)).task;
          setResolution({ memo, current: current.title, version: current.version });
        })}>查看服务器版本并解决</button>}
      </li>)}</ul>
    </section>}
    {visible && resolution && <section aria-label="解决备忘冲突"><p>服务器内容：{resolution.current}</p><p>本地内容：{resolution.memo.title}</p>
      <button disabled={busy} onClick={() => void run(async () => {
        await setQueue(current => current.map(row => row.request_id === resolution.memo.request_id ? {
          request_id: crypto.randomUUID(), title: row.title, task_id: row.task_id, expected_version: resolution.version,
        } : row)); setResolution(undefined);
      })}>保留本地修改，使用已查看的版本重新排队</button>
      <button onClick={() => setResolution(undefined)}>稍后解决</button></section>}
  </section></main>;
}
