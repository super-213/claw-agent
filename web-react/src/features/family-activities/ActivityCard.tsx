import { isImmediateUpdate } from '../pwa/updateState';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { activityData, type ActivityAction, type ActivityView } from '../../api/familyActivities';
import type { CardRenderProps } from '../interactive-cards/types';
import { forgetCardEdit, readCardEdit, writeCardEdit } from '../interactive-cards/state';
import { boardTime } from '../board/boardTime';
import { ActivityFields } from './ActivityFields';
import './activities.css';

type SavedForm = { value: ReturnType<typeof activityData>; version: number };
export function ActivityCard(props: CardRenderProps<ActivityView, ActivityAction>) {
  if (props.view.destroyed) return <aside className="interactive-card" role="status">该家庭活动已销毁。</aside>;
  return <LiveActivityCard {...props} />;
}
function LiveActivityCard({ view, context, editKey, submit, busy, verifying, uncertain, error, retry, refresh, savedSequence }: CardRenderProps<ActivityView, ActivityAction>) {
  const navigate = useNavigate();
  const row = view.activity;
  const cached = readCardEdit<SavedForm>(editKey);
  const initialForm = () => { const value = activityData(row); if (row.kind === 'poll' && !value.options.length) value.options = [{ id: 'option_1', text: '' }, { id: 'option_2', text: '' }]; return { value, version: row.version }; };
  const [form, setForm] = useState<SavedForm>(() => cached || initialForm());
  const [editing, setEditing] = useState(row.state === 'draft' || !!cached);
  const [choices, setChoices] = useState(view.own_participation?.option_ids || []);
  const [values, setValues] = useState(view.own_participation?.values || {});
  const [ownVersion, setOwnVersion] = useState(view.participation_version);
  const [confirming, setConfirming] = useState<'delete' | 'close' | null>(null);
  const [localError, setLocalError] = useState('');
  const [expired, setExpired] = useState(false);
  const [deadlineReached, setDeadlineReached] = useState(false);
  const refreshRef = useRef(refresh); refreshRef.current = refresh;
  useEffect(() => {
    const observed = performance.now();
    const server = Date.parse(view.server_now);
    let timer = 0;
    const check = () => {
      const now = server + performance.now() - observed;
      const expiry = Date.parse(view.valid_until || '');
      const deadline = Date.parse(row.participation_deadline_at || '');
      setExpired(Number.isFinite(expiry) && now >= expiry);
      setDeadlineReached(Number.isFinite(deadline) && now >= deadline);
      const future = [expiry, row.state === 'open' ? deadline : NaN].filter(t => Number.isFinite(t) && t > now);
      if (future.length) timer = window.setTimeout(() => { check(); refreshRef.current(); }, Math.min(2147483647, Math.max(20, Math.min(...future) - now + 10)));
    };
    check(); return () => clearTimeout(timer);
  }, [view.server_now, view.valid_until, row.participation_deadline_at, row.state]);
  const previousSave = useRef(savedSequence);
  useEffect(() => {
    if (previousSave.current === savedSequence) return;
    previousSave.current = savedSequence;
    setForm(initialForm()); setEditing(row.state === 'draft'); setConfirming(null);
    setChoices(view.own_participation?.option_ids || []); setValues(view.own_participation?.values || {}); setOwnVersion(view.participation_version);
  }, [savedSequence]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const warn = (event: globalThis.BeforeUnloadEvent) => { if (isImmediateUpdate()) return; if (readCardEdit(editKey)) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, [editKey]);
  const locked = busy || verifying || uncertain;
  const can = (action: string) => view.capabilities.actions.includes(action);
  const name = (id: string) => view.members.find(m => m.member_id === id)?.display_name || '家庭成员';
  const title = row.kind === 'poll' ? '家庭投票' : '家庭接龙';
  const send = async (action: ActivityAction['action']) => {
    setLocalError('');
    const data: ActivityAction['data'] = action === 'participate' ? row.kind === 'poll' ? { option_ids: choices } : { values }
      : ['save', 'save_draft', 'publish'].includes(action) ? { ...form.value, options: form.value.options.filter(o => o.text.trim()) } : {};
    try { await submit({ action, target: view.resource, expected_version: ['save', 'save_draft', 'publish'].includes(action) ? form.version : row.version, participation_version: ownVersion, data }); }
    catch (caught) { setLocalError((caught as Error).message); }
  };
  if (expired) return <aside className="interactive-card" role="status">该家庭活动已到存在截止时间，无法查看。</aside>;
  return <article className="interactive-card board-chat-card activity-card" aria-label={`${title}卡片`}>
    <header className="board-card-heading"><strong>{title}{row.state === 'draft' ? '草稿 · 尚未发布' : ''}</strong><span>{({ draft: '未发布', open: deadlineReached ? '正在核实截止' : '进行中', closed: '已结束' })[row.state]}</span></header>
    {editing && view.capabilities.editable_fields.length > 0 ? <ActivityFields value={form.value} onChange={value => { const next = { value, version: form.version }; setForm(next); writeCardEdit(editKey, next); }} kind={row.kind} timezone={view.timezone} editable={view.capabilities.editable_fields} disabled={locked} /> : <>
      <h3>{row.title}</h3>{row.description && <p className="activity-description">{row.description}</p>}
      <p className="board-card-meta">{name(row.created_by)} 发起 · 家庭成员实名参与</p>
      <p className="board-card-meta">参与截止：{row.participation_deadline_at ? boardTime(row.participation_deadline_at, view.timezone) : '不设截止'}<br />存在截止：{row.expires_at ? boardTime(row.expires_at, view.timezone) : '长期保留'}（{view.timezone}）</p>
      <p>{view.participants.length} 人已参与{row.kind === 'relay' && row.capacity ? ` / ${row.capacity} 个名额` : ''}{view.own_participation ? ' · 你已参与' : ''}</p>
      {row.auto_close && <p className="board-card-meta">发布时全员完成自动结束（包含创建者）；当前有效目标 {row.completion_member_ids.filter(id => view.members.some(m => m.member_id === id && m.status === 'active')).length} 人。</p>}
      {row.state === 'closed' && <p role="status">{({ deadline: '已到参与截止时间', all_completed: '全员已完成', capacity: '接龙名额已满', manual: '创建者已主动结束' })[row.close_reason || ''] || '活动已结束'}，结果只读。</p>}
      {row.kind === 'poll' ? <fieldset className="activity-ballot" disabled={locked || !can('participate') || deadlineReached}>
        <legend>{row.multiple ? `多选，选择 ${row.min_choices}—${row.max_choices} 项` : '单选'} · 实名投票</legend>
        {row.options.map(option => { const count = row.counts?.[option.id] || 0; const percent = view.participants.length ? Math.round(100 * count / view.participants.length) : 0; return <label className="activity-vote-option" key={option.id}>
          <input type={row.multiple ? 'checkbox' : 'radio'} name={`vote-${editKey}`} value={option.id} checked={choices.includes(option.id)} onChange={e => setChoices(row.multiple ? e.target.checked ? [...choices, option.id] : choices.filter(id => id !== option.id) : [option.id])} />
          <span>{option.text}<span className="activity-vote-track"><span style={{ width: `${percent}%` }} /></span></span><small>{count} 票 · {percent}%</small>
        </label>; })}
        {row.multiple && <p className="board-card-meta">比例按参与人数计算，多选合计可能超过 100%。</p>}
      </fieldset> : <>
        <ol className="activity-entries">{view.participants.map(person => <li key={person.member_id} value={person.sequence}><strong>{name(person.member_id)}</strong><span>{Object.values(person.values || {}).filter(v => v !== null).join(' · ')}</span></li>)}</ol>
        {can('participate') && !deadlineReached && <fieldset className="board-fields" disabled={locked}>{(row.fields.length ? row.fields : [{ id: 'content', label: '接龙内容', type: 'text' as const, required: true }]).map(field => <label key={field.id}>{field.label}{field.required ? '（必填）' : ''}<input maxLength={2000} type={field.type === 'number' ? 'number' : 'text'} step={field.type === 'number' ? 'any' : undefined} value={values[field.id] ?? ''} onChange={e => setValues({ ...values, [field.id]: field.type === 'number' ? e.target.value === '' ? null : Number(e.target.value) : e.target.value })} /></label>)}</fieldset>}
      </>}
      {row.kind === 'poll' && view.participants.length > 0 && <details className="activity-participants"><summary>查看实名投票记录</summary>{view.participants.map(person => <p key={person.member_id}>{name(person.member_id)}：{row.options.filter(o => person.option_ids?.includes(o.id)).map(o => o.text).join('、')}</p>)}</details>}
    </>}
    {row.state === 'draft' && row.missing_fields.length > 0 && <p className="board-card-meta">待补充：{row.missing_fields.join('、')}</p>}
    {(localError || error) && <p role="alert" className="board-error">{error || localError}</p>}
    {editing && form.version !== row.version && <p role="alert">活动已有新版本，输入已保留，请重新读取后核对。</p>}
    {!editing && ownVersion !== view.participation_version && <p role="alert">你的参与记录已有新版本，请重新读取后再提交。</p>}
    <div className="board-card-actions">
      {editing && <>
        {can('save_draft') && <button type="button" disabled={locked || form.version !== row.version} onClick={() => void send('save_draft')}>保存草稿</button>}
        {(can('publish') || can('save')) && <button type="button" className="board-primary" disabled={locked || form.version !== row.version} onClick={() => void send(row.state === 'draft' ? 'publish' : 'save')}>{busy ? '正在保存…' : row.state === 'draft' ? `发布${title}` : '保存修改'}</button>}
      </>}
      {!editing && can('participate') && !deadlineReached && <button type="button" className="board-primary" disabled={locked || ownVersion !== view.participation_version} onClick={() => void send('participate')}>{view.own_participation ? row.kind === 'poll' ? '保存改票' : '修改本人接龙' : row.kind === 'poll' ? '提交投票' : '加入接龙'}</button>}
      {!editing && can('withdraw') && !deadlineReached && <button type="button" disabled={locked || ownVersion !== view.participation_version} onClick={() => void send('withdraw')}>撤回本人{row.kind === 'poll' ? '选票' : '接龙'}</button>}
      {!editing && can('save') && <button type="button" disabled={locked} onClick={() => { setForm(initialForm()); setEditing(true); }}>管理活动</button>}
      {!editing && can('close') && <button type="button" disabled={locked} onClick={() => setConfirming('close')}>结束活动</button>}
      {can('delete') && <button type="button" disabled={locked} onClick={() => setConfirming('delete')}>{row.state === 'draft' ? '删除草稿' : '删除活动'}</button>}
      <button type="button" disabled={locked} onClick={() => { forgetCardEdit(editKey); setForm(initialForm()); setChoices(view.own_participation?.option_ids || []); setValues(view.own_participation?.values || {}); setOwnVersion(view.participation_version); setEditing(row.state === 'draft'); refresh(); }}>重新读取</button>
      {context.surface === 'chat' && row.state !== 'draft' && <button type="button" onClick={() => navigate(`/home?panel=board&activity=${encodeURIComponent(row.id)}`)}>在留言板查看</button>}
      {uncertain && <button type="button" disabled={busy || verifying} onClick={retry}>核实并重试</button>}
    </div>
    {confirming && <div className="activity-confirm" role="alert"><p>{confirming === 'delete' ? '删除将立即销毁活动及全部参与数据，无法恢复。' : '结束后不能继续参与或重新开放。'}</p><button type="button" disabled={locked} onClick={() => void send(confirming)}>确认{confirming === 'delete' ? '删除' : '结束'}</button><button type="button" disabled={locked} onClick={() => setConfirming(null)}>取消</button></div>}
  </article>;
}
