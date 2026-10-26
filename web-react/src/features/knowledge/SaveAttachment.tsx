import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { knowledgeApi, operationId, type KnowledgeEntry } from '../../api/knowledge';
import type { Message, MessageMedia } from '../../api/types';
import { useAppStore } from '../../stores/appStore';
import './knowledge.css';

export function SaveAttachment({ media, message }: { media: MessageMedia; message: Message }) {
  const sessionId = useAppStore((s) => s.currentSessionId);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(String(media.name || media.alt || '生活资料'));
  const [objectName, setObjectName] = useState('');
  const [saved, setSaved] = useState<KnowledgeEntry | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [requestId] = useState(operationId);
  const path = String(media.path || media.url || '');
  if (!sessionId || !message.node_id || !path || /^https?:|^data:/i.test(path)) return null;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try {
      const row = await knowledgeApi.saveDocument({ path, title, object_name: objectName, request_id: requestId,
        source_session_id: sessionId, source_node_id: message.node_id });
      setSaved(row); setEditing(false);
      window.dispatchEvent(new CustomEvent('knowledge_changed'));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <div className="knowledge-attachment-action">
    {saved ? <p role="status">{saved.status === 'ready' ? '已保存，可跨会话检索' : saved.status === 'partial' ? '已保存，部分内容可检索' : '原文件已保存，正文处理失败'} · 仅自己可见 <Link to={`/home/library?id=${saved.id}`}>查看资料</Link></p>
      : editing ? <form className="knowledge-inline-form" onSubmit={(event) => void submit(event)}>
        <label>资料名称<input value={title} maxLength={500} required onChange={(e) => setTitle(e.target.value)} /></label>
        <label>关联对象（选填）<input value={objectName} maxLength={500} placeholder="例如：客厅空调" onChange={(e) => setObjectName(e.target.value)} /></label>
        <p>保存后仅自己可见，可在资料中选择共享。</p>
        <div><button type="submit" disabled={busy}>{busy ? '正在保存与处理…' : '确认保存'}</button><button type="button" disabled={busy} onClick={() => setEditing(false)}>取消</button></div>
      </form> : <button type="button" onClick={() => setEditing(true)}>保存到资料</button>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
