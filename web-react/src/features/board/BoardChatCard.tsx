import { isImmediateUpdate } from '../pwa/updateState';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { boardAssetUrl, boardData, type BoardAction, type BoardData, type BoardView } from '../../api/board';
import { HomeDialog } from '../../components/ui/HomeDialog';
import type { CardRenderProps } from '../interactive-cards/types';
import { readCardEdit, writeCardEdit, readCardAttachments } from '../interactive-cards/state';
import { BoardFields } from './BoardFields';
import { BoardBody } from './BoardNote';
import { boardTime } from './boardTime';
import './board.css';

export function BoardChatCard({ view, context, editKey, busy, verifying, uncertain, error, retry, refresh, submit, savedSequence }: CardRenderProps<BoardView, BoardAction>) {
  const navigate = useNavigate();
  const cached = readCardEdit<{ value: BoardData; version: number }>(editKey);
  const [edit, setEdit] = useState(() => view.mode === 'draft' || !!cached);
  const [form, setForm] = useState(() => cached || { value: boardData(view.post), version: view.post.version });
  const [uploading, setUploading] = useState(() => !!readCardAttachments<unknown[]>(editKey)?.length);
  const [localError, setLocalError] = useState('');
  const [image, setImage] = useState<string | null>(null);
  const [ended, setEnded] = useState(false);
  const refreshRef = useRef(refresh); refreshRef.current = refresh;
  useEffect(() => {
    const remaining = Date.parse(view.valid_until || '') - Date.parse(view.server_now);
    setEnded(Number.isFinite(remaining) && remaining <= 0);
    if (!Number.isFinite(remaining) || remaining <= 0) return;
    const observed = performance.now();
    let timer = 0;
    const check = () => {
      const left = remaining - (performance.now() - observed);
      if (left > 0) { timer = window.setTimeout(check, Math.min(left + 20, 2147483647)); return; }
      setEnded(true); setImage(null); refreshRef.current();
    };
    timer = window.setTimeout(check, Math.min(remaining + 20, 2147483647));
    return () => clearTimeout(timer);
  }, [view.valid_until, view.server_now]);
  useEffect(() => {
    const warn = (event: globalThis.BeforeUnloadEvent) => { if (isImmediateUpdate()) return; if (readCardEdit(editKey)) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [editKey]);
  const previousSave = useRef(savedSequence);
  useEffect(() => {
    if (previousSave.current === savedSequence) return;
    previousSave.current = savedSequence;
    setForm({ value: boardData(view.post), version: view.post.version }); setEdit(view.mode === 'draft');
  }, [savedSequence]); // eslint-disable-line react-hooks/exhaustive-deps
  const change = (value: BoardData) => { const next = { ...form, value }; setForm(next); writeCardEdit(editKey, next); };
  const act = async (action: BoardAction['action']) => {
    setLocalError('');
    try {
      await submit({ action, target: view.resource, expected_version: form.version, data: action === 'withdraw' ? {} : form.value });
    } catch (caught) { if (!(caught instanceof Error)) setLocalError('保存失败，请重试。'); }
  };
  const canEdit = view.capabilities.editable_fields.length > 0;
  const locked = busy || verifying || uncertain || uploading || !canEdit || form.version !== view.post.version;
  if (ended || view.post.state === 'expired') return <aside className="interactive-card card-fallback" role="status">{view.mode === 'draft' ? '便笺草稿已失效。' : '便笺已到期，无法查看。'}</aside>;
  return <article className={`interactive-card board-chat-card ${context.surface === 'workbench_board' ? 'board-workbench-card' : ''}`} aria-label={view.mode === 'draft' ? '便笺草稿卡片' : `便笺卡片：${view.post.title || '未命名便笺'}`}>
    <header className="board-card-heading"><strong>{view.mode === 'draft' ? '便笺草稿 · 尚未发布' : '留言板便笺'}</strong><span>{({ draft: '未发布', active: '已发布', expired: '已到期', withdrawn: '已撤下' })[view.post.state]}</span></header>
    {/* Returning from the native photo picker triggers a permission refresh.
        Keep local inputs active so its change event is not discarded; submission
        stays locked by verifying and every upload still requires server authorization. */}
    {edit && canEdit ? <BoardFields editKey={editKey} value={form.value} onChange={change} members={view.members} timezone={view.timezone} disabled={busy || uncertain} onUploading={setUploading} /> : <div className="board-card-read"><BoardBody view={view} onPreview={setImage} />
      <p className="board-card-meta">{view.members.find(m => m.member_id === view.post.created_by)?.display_name || '家庭成员'} · {boardTime(view.post.published_at || view.post.created_at, view.timezone)}<br />{view.post.audience_mode === 'household' ? '当前家庭所有人' : view.post.recipient_ids.map(id => view.members.find(m => m.member_id === id)?.display_name || '家庭成员').join('、')} · {view.post.expires_at ? `${boardTime(view.post.expires_at, view.timezone)} 截止（${view.timezone}）` : '长期保留'}</p>
    </div>}
    {view.mode === 'draft' && !!view.post.missing_fields?.length && !edit && <p>待补充：{view.post.missing_fields.join('、')}</p>}
    {edit && form.version !== view.post.version && <p role="alert">便笺已有新版本，输入已保留。请核对后重新编辑。</p>}
    {(error || localError) && <p className="board-error" role="alert">{error || localError}</p>}
    {verifying && <p role="status">正在核实最新权限与状态…</p>}
    <div className="board-card-actions">
      {canEdit && !edit && <button type="button" disabled={busy || verifying} onClick={() => { setForm({ value: boardData(view.post), version: view.post.version }); setEdit(true); }}>编辑便笺</button>}
      {edit && canEdit && <>
        {view.mode === 'draft' && <button type="button" disabled={locked} onClick={() => void act('save_draft')}>保存草稿</button>}
        <button type="button" className="board-primary" disabled={locked} onClick={() => void act(view.mode === 'draft' ? 'publish' : 'save')}>{busy ? '正在保存…' : view.mode === 'draft' ? '发布便笺' : '保存修改'}</button>
        <button type="button" disabled={busy || uncertain || uploading} onClick={() => { setForm({ value: boardData(view.post), version: view.post.version }); setEdit(view.mode === 'draft'); refresh(); }}>重新读取</button>
      </>}
      {view.mode === 'saved' && context.surface === 'chat' && <button type="button" onClick={() => navigate(`/home?panel=board&post=${encodeURIComponent(view.post.id)}`)}>在留言板查看</button>}
      {view.capabilities.actions.includes('withdraw') && !edit && <button type="button" disabled={busy || verifying || uncertain} onClick={() => void act('withdraw')}>撤下便笺</button>}
      {uncertain && <button type="button" onClick={retry} disabled={busy || verifying}>核实并重试</button>}
    </div>
    {image && <HomeDialog className="board-dialog" title="便笺图片" onClose={() => setImage(null)} wide><img className="board-full-image" src={boardAssetUrl(image)} alt="便笺图片预览" /></HomeDialog>}
  </article>;
}
