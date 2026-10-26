import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BookOpen, FilePlus2, Plus, Search } from 'lucide-react';
import { chatApi } from '../../api/chat';
import { knowledgeApi, operationId, type KnowledgeCollection, type KnowledgeEntry, type KnowledgeMatch } from '../../api/knowledge';
import { useAppStore } from '../../stores/appStore';
import { HomeDialog } from '../../components/ui/HomeDialog';
import './knowledge.css';

const statusLabels: Record<string, string> = { ready: '可检索', partial: '部分可检索', failed: '正文处理失败', active: '有效记录', outdated: '已过时' };

export function KnowledgeView({ collection }: { collection: KnowledgeCollection }) {
  const user = useAppStore((s) => s.currentUser);
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState<KnowledgeMatch[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ title: '', object_name: '', content: '', kind: 'fact', aliases: '' });
  const [deleting, setDeleting] = useState(false);
  const [shareConfirm, setShareConfirm] = useState(false);
  const [upload, setUpload] = useState<File | null>(null);
  const selectedId = params.get('id');
  const list = useQuery({ queryKey: ['knowledge', user?.id, collection], queryFn: () => knowledgeApi.list(collection), refetchOnWindowFocus: true });
  const detail = useQuery({ queryKey: ['knowledge', user?.id, collection, selectedId],
    queryFn: () => knowledgeApi.get(collection, selectedId!), enabled: Boolean(selectedId) });
  const selected = detail.data;
  const refresh = () => client.invalidateQueries({ queryKey: ['knowledge'] });
  useEffect(() => {
    const invalidate = () => { void client.invalidateQueries({ queryKey: ['knowledge'] }); };
    window.addEventListener('knowledge_changed', invalidate);
    return () => window.removeEventListener('knowledge_changed', invalidate);
  }, [client]);
  useEffect(() => {
    setDraft({ title: selected?.title || '', object_name: selected?.object_name || '', content: selected?.content || '',
      kind: selected?.kind || 'fact', aliases: (selected?.aliases || []).join('，') });
    setDeleting(false); setShareConfirm(false); setError('');
  }, [selected]);
  const close = () => { const next = new URLSearchParams(params); next.delete('id'); setParams(next, { replace: true }); setCreating(false); };
  const run = async (action: () => Promise<unknown>, message: string, after?: () => void) => {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await action(); setNotice(message); await refresh(); setMatches(null); after?.(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const save = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      if (selected) {
        await knowledgeApi.change(collection, selected, { title: draft.title, object_name: draft.object_name,
          aliases: draft.aliases.split(/[,，]/).map((s) => s.trim()).filter(Boolean), ...(collection === 'records' ? { content: draft.content } : {}) });
      } else if (collection === 'records') {
        await knowledgeApi.saveRecord({ title: draft.title, content: draft.content, object_name: draft.object_name,
          kind: draft.kind, request_id: operationId() });
      } else if (upload) {
        const uploaded = await chatApi.uploadMedia([upload]);
        await knowledgeApi.saveDocument({ path: String(uploaded.media[0].path), title: draft.title || upload.name,
          object_name: draft.object_name, request_id: operationId() });
      }
    }, '已保存。新资料和记录默认仅自己可见；处理状态见列表。', close);
  };
  const replace = async (row: KnowledgeEntry, file: File) => {
    const uploaded = await chatApi.uploadMedia([file]);
    return knowledgeApi.saveDocument({ path: String(uploaded.media[0].path), request_id: operationId(), title: row.title,
      object_name: row.object_name, replace_id: row.id, expected_version: row.version });
  };
  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) { setMatches(null); return; }
    setBusy(true); setError('');
    try { setMatches((await knowledgeApi.search(query)).items.filter((m) => m.collection === collection)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const owner = selected?.owner_user_id === user?.id;
  return <section className="knowledge-view" aria-label={collection === 'documents' ? '生活资料' : '生活记忆'}>
    <div className="knowledge-heading"><div><h2>{collection === 'documents' ? '生活资料' : '生活记忆'}</h2>
      <p>{collection === 'documents' ? '留下说明书、图片和文件，以后接着问。' : '记住位置、发生过的事和个人偏好。'}</p></div>
      <button type="button" className="home-primary" onClick={() => { setDraft({ title: '', object_name: '', content: '', kind: 'fact', aliases: '' }); setUpload(null); setCreating(true); }}><Plus size={17} />{collection === 'documents' ? '保存资料' : '记一件事'}</button></div>
    <form className="knowledge-search" onSubmit={(e) => void search(e)}><label className="sr-only" htmlFor="knowledge-query">搜索已保存内容</label>
      <input id="knowledge-query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="按名称、对象或内容查找…" /><button type="submit" disabled={busy}><Search size={17} />查找</button></form>
    {notice && <p role="status" className="home-feedback">{notice}</p>}
    {error && !selected && !creating && <p role="alert" className="home-error">{error}</p>}
    {list.isPending && <p role="status">正在读取…</p>}
    {list.isError && <p role="alert">读取失败。<button onClick={() => void list.refetch()}>重试</button></p>}
    {detail.isError && <p role="alert">该内容已删除或无权访问。<button onClick={close}>返回列表</button></p>}
    {matches ? <div className="knowledge-results"><p>{matches.length ? '找到以下来源' : '没有找到相关记录，可换一种说法或上传材料。'}</p>
      {matches.map((match) => <article key={match.source_url}><h3>{match.title} · {match.location}</h3><p>{match.text}</p><a href={match.source_url} target="_blank" rel="noreferrer">核对来源</a></article>)}</div>
      : <div className="knowledge-list">{list.data?.items.map((row) => <button className="knowledge-row" key={row.id} onClick={() => setParams({ id: row.id })}>
        <BookOpen size={20} /><span><strong>{row.title}</strong><small>{[row.object_name, statusLabels[row.status] || row.status, row.visibility === 'household' ? '家庭共享' : '仅自己可见'].filter(Boolean).join(' · ')}</small></span>
        <time dateTime={row.updated_at}>{new Date(row.updated_at).toLocaleDateString('zh-CN')}</time></button>)}
        {list.data && !list.data.items.length && <div className="knowledge-empty"><FilePlus2 size={30} /><p>{collection === 'documents' ? '保存第一份生活资料，或在对话中发送文件并选择保存。' : '把值得记住的信息留在这里，也可以在对话中说“帮我记住”。'}</p><Link to="/chat">去对话</Link></div>}</div>}
    {(selected || creating) && <HomeDialog title={selected ? selected.title : collection === 'documents' ? '保存生活资料' : '记住生活信息'} onClose={close}>
      <form className="knowledge-form" onSubmit={save}>
        {!selected && collection === 'documents' && <label>选择文件<input type="file" required onChange={(e) => { const file = e.target.files?.[0]; if (file) { setUpload(file); setDraft((d) => ({ ...d, title: file.name })); } }} /></label>}
        <label>名称<input required maxLength={500} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
        <label>关联对象（选填）<input maxLength={500} value={draft.object_name} placeholder="例如：客厅空调" onChange={(e) => setDraft({ ...draft, object_name: e.target.value })} /></label>
        {collection === 'records' && <><div className="knowledge-field"><label htmlFor="knowledge-record-content">内容</label><textarea id="knowledge-record-content" required rows={4} maxLength={20000} value={draft.content} onChange={(e) => setDraft({ ...draft, content: e.target.value })} /></div>
          {!selected && <label>记录类型<select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}><option value="fact">信息</option><option value="event">发生记录</option><option value="preference">个人偏好</option></select></label>}</>}
        {selected && <label>其他称呼（用逗号分隔）<input value={draft.aliases} onChange={(e) => setDraft({ ...draft, aliases: e.target.value })} /></label>}
        {error && <div><p role="alert">{error}</p>{selected && <button type="button" disabled={busy} onClick={() => void detail.refetch()}>读取最新版本</button>}</div>}
        <button className="home-primary" type="submit" disabled={busy}>{busy ? '正在处理…' : '保存'}</button>
      </form>
      {selected ? <div className="knowledge-detail-actions">
        <p>{statusLabels[selected.status]} · {selected.visibility === 'household' ? '家庭成员可见' : '仅自己可见'} · 更新于 {new Date(selected.updated_at).toLocaleString('zh-CN')}</p>
        {selected.warnings?.map((warning) => <p role="status" key={warning}>{warning}</p>)}
        {selected.file_url && <a href={selected.file_url} target="_blank" rel="noreferrer">打开原文件</a>}
        {selected.source?.session_id && <Link to={`/sessions/${selected.source.session_id}`}>查看来源对话</Link>}
        {selected.source?.text && <details><summary>原始记录</summary><p>{selected.source.text}</p></details>}
        {collection === 'documents' && owner && <><button disabled={busy} onClick={() => void run(() => knowledgeApi.reprocess(selected), '已重新处理，请查看处理状态。')}>重新处理正文</button>
          <label>替换原文件<input type="file" disabled={busy} onChange={(e) => { const file = e.target.files?.[0]; if (file) void run(() => replace(selected, file), '已替换；后续检索使用新版本。'); }} /></label></>}
        {collection === 'records' && <button disabled={busy} onClick={() => void run(() => knowledgeApi.change(collection, selected, { status: selected.status === 'outdated' ? 'active' : 'outdated' }), '记录状态已更新。')}>{selected.status === 'outdated' ? '恢复为有效记录' : '标记过时'}</button>}
        {owner && <>
          <button disabled={busy} onClick={() => selected.visibility === 'personal' ? setShareConfirm(true)
            : void run(() => knowledgeApi.change(collection, selected, { visibility: 'personal' }), '已撤回共享；历史聊天中的内容仍保留。')}>{selected.visibility === 'personal' ? '共享给家庭' : '撤回共享'}</button>
          {shareConfirm && <div className="knowledge-confirm"><p>共享后，当前有效家庭成员可检索正文并更正信息。确定共享这条内容？</p><button disabled={busy} onClick={() => void run(() => knowledgeApi.change(collection, selected, { visibility: 'household' }), '已共享给家庭。', () => setShareConfirm(false))}>确认共享</button><button disabled={busy} onClick={() => setShareConfirm(false)}>取消</button></div>}
          <button disabled={busy} onClick={() => setDeleting(true)}>删除{collection === 'documents' ? '资料' : '记录'}</button>
          {deleting && <div className="knowledge-confirm"><p>删除后停止检索，并删除资料库副本。原上传文件及历史聊天中的内容仍保留。</p><button disabled={busy} onClick={() => void run(() => knowledgeApi.remove(collection, selected), '已删除；原上传文件和历史聊天保留。', close)}>确认删除</button><button disabled={busy} onClick={() => setDeleting(false)}>取消</button></div>}
        </>}
        {!!selected.history?.length && <details><summary>更新记录</summary><ul>{selected.history.map((event, i) => <li key={i}>{new Date(event.at).toLocaleString('zh-CN')} · {event.action === 'save' ? '保存' : event.action === 'replace' ? '替换资料' : '更新'} · {event.by === user?.id ? '我' : '家庭成员'}</li>)}</ul></details>}
      </div> : <p className="knowledge-muted">保存后仅自己可见。未来安排与待办请在事项中记录。</p>}
    </HomeDialog>}
  </section>;
}
