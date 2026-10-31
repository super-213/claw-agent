import { isImmediateUpdate } from '../pwa/updateState';
import { CalendarDays, StickyNote, UsersRound } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { CardRenderProps } from '../interactive-cards/types';
import { forgetCardEdit, readCardEdit, writeCardEdit } from '../interactive-cards/state';
import { InteractiveCardHost } from '../interactive-cards/InteractiveCardHost';
import { cardTimestamp, localCardTime } from './taskCardTime';
import type { DraftTaskItem, TaskCardAction, TaskCardView } from './taskCardAdapter';

interface FormValue {
  title: string; description: string; day: string; time: string; temporal: string; space: string;
  members: string[]; completion: string; weekly: boolean; weekday: string; status: string; scope: string;
  literal: boolean;
}
interface SavedEdit { form: FormValue; baseline: FormValue; taskVersion: number; occurrenceVersion: number; editing: boolean }
function formFor(view: TaskCardView, scope?: string): FormValue {
  const task = view.task!;
  const occ = view.occurrence;
  const currentScope = scope || (task.recurrence ? 'occurrence' : 'single');
  const future = currentScope === 'future';
  const stamp = localCardTime(future ? task.due_at : occ?.due_at || task.due_at, view.timezone);
  return { title: (!future && occ?.title_snapshot) || task.title, description: task.description || '',
    day: (future ? task.due_date : occ?.due_date || task.due_date) || '', time: stamp.slice(11, 16), temporal: task.temporal_type,
    space: task.space_type, members: (!future && occ?.assignee_ids) || task.assignee_ids,
    completion: (!future && occ?.completion_mode) || task.completion_mode || 'all',
    weekly: !!task.recurrence, weekday: task.recurrence?.weekday || '',
    status: occ?.member_progress[view.current_member_id]?.status || occ?.status || 'open',
    scope: currentScope, literal: task.temporal_type === 'undated' && hasTimeText(task.title + task.description) };
}
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const hasTimeText = (text: string) => /今天|明天|后天|下周|本周|每周|每天|每月|周[一二三四五六日天]|\d{4}-\d{2}-\d{2}|\d+月\d+[日号]/.test(text);
const statuses: Record<string, string> = { open: '未完成', completed: '已完成', cancelled: '已取消', skipped: '已跳过', information: '信息记录' };
const timeStates: Record<string, string> = { upcoming: '待进行', in_progress: '当天 · 正在进行', expired: '已过期', undated: '无日期', draft: '待补充' };
const reasons: Record<string, string> = { expired: '该事项已过期，仅供查看。', completed: '该事项已完成。',
  archived: '该事项已归档，仅供查看。', cancelled: '该事项已取消，仅供查看。', skipped: '本期已跳过。', paused: '该系列已暂停。', not_permitted: '你可以查看这条记录。' };

export function TaskChatCard(props: CardRenderProps<TaskCardView, TaskCardAction>) {
  return props.view.mode === 'draft' ? <DraftCard {...props} /> : <SavedCard {...props} />;
}

function SavedCard({ view, context, editKey, submit, busy, verifying, uncertain, error, retry, refresh, savedSequence }: CardRenderProps<TaskCardView, TaskCardAction>) {
  const task = view.task!;
  const occ = view.occurrence;
  const [edit, setEdit] = useState<SavedEdit>(() => readCardEdit<SavedEdit>(editKey) || {
    form: formFor(view), baseline: formFor(view), taskVersion: task.version, occurrenceVersion: occ?.version || 0, editing: false });
  const serverForm = formFor(view, edit.form.scope);
  const [localError, setLocalError] = useState('');
  const dirty = !equal(edit.form, edit.baseline);
  const conflict = dirty && (edit.taskVersion !== task.version || edit.occurrenceVersion !== (occ?.version || 0));
  const actions = view.capabilities.actions;
  const canEdit = view.capabilities.editable_fields.length > 0;
  const locked = busy || verifying || uncertain || (view.read_only && !actions.length);
  const fieldLocked = locked || !canEdit;
  const form = edit.form;
  const name = (id: string) => view.members.find(m => m.member_id === id)?.display_name || '已停用成员';
  useEffect(() => { if (edit.editing || dirty) writeCardEdit(editKey, edit); else forgetCardEdit(editKey); }, [edit, dirty, editKey]);
  useEffect(() => {
    if (!savedSequence) return;
    const latest = formFor(view);
    setEdit({ form: latest, baseline: latest, taskVersion: view.task!.version, occurrenceVersion: view.occurrence?.version || 0, editing: false });
    setLocalError('');
    // Only this placement's successful submission resets its local editor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedSequence]);
  useEffect(() => {
    if (!dirty) setEdit(current => ({ ...current, form: formFor(view, current.form.scope), baseline: formFor(view, current.form.scope), taskVersion: task.version, occurrenceVersion: occ?.version || 0 }));
  }, [view, task.version, occ?.version, dirty]);
  useEffect(() => {
    if (!dirty) return;
    const leave = (event: Event) => { if (isImmediateUpdate()) return; event.preventDefault(); event.returnValue = true; };
    window.addEventListener('beforeunload', leave);
    return () => window.removeEventListener('beforeunload', leave);
  }, [dirty]);
  const update = <K extends keyof FormValue>(key: K, value: FormValue[K]) => {
    setLocalError(''); setEdit(e => ({ ...e, form: { ...e.form, [key]: value } }));
  };
  const rebase = () => {
    const latest = formFor(view, form.scope);
    const merged = { ...latest };
    for (const key of Object.keys(form) as Array<keyof FormValue>) {
      if (!equal(form[key], edit.baseline[key])) Object.assign(merged, { [key]: form[key] });
    }
    setEdit({ ...edit, form: merged, baseline: latest, taskVersion: task.version, occurrenceVersion: occ?.version || 0 });
  };
  const apply = async (payload: TaskCardAction) => {
    setLocalError('');
    try {
      const result = await submit({ ...payload, target: { resource: view.resource } });
      forgetCardEdit(editKey);
      const current = formFor(result);
      setEdit({ form: current, baseline: current, taskVersion: result.task!.version, occurrenceVersion: result.occurrence?.version || 0, editing: false });
    } catch (caught) { setLocalError((caught as Error).message); }
  };
  const basePayload = (): TaskCardAction => ({ expected_task_version: edit.taskVersion,
    occurrence_id: view.resource.instance_id, expected_occurrence_version: edit.occurrenceVersion, scope: form.scope });
  const save = async () => {
    if (conflict || locked) return;
    try {
      if (!form.title.trim()) throw new Error('请填写事项标题。');
      const payload = basePayload();
      const patch: Record<string, unknown> = {};
      const mapping: Array<[keyof FormValue, string]> = [['title', 'title'], ['description', 'description'], ['space', 'space_type'],
        ['temporal', 'temporal_type'], ['members', 'assignee_ids'], ['completion', 'completion_mode']];
      for (const [key, property] of mapping) if (!equal(form[key], edit.baseline[key])) patch[property] = form[key];
      if (form.temporal === 'undated' && edit.baseline.temporal !== 'undated') Object.assign(patch, { due_date: null, due_at: null, recurrence: null, starts_on: null });
      else if (form.day !== edit.baseline.day || form.time !== edit.baseline.time || form.temporal !== edit.baseline.temporal) {
        if (!form.day && !form.weekly) throw new Error('日程需要日期。');
        if (form.time && !form.day) throw new Error('选择具体时间时请同时补充日期。');
        Object.assign(patch, { due_date: form.day || null, due_at: cardTimestamp(form.day, form.time, view.timezone) });
      }
      if (form.temporal === 'timed' && (form.weekly !== edit.baseline.weekly || form.weekday !== edit.baseline.weekday)) {
        patch.recurrence = form.weekly ? { frequency: 'weekly', weekday: form.weekday || null } : null;
      }
      if (form.literal !== edit.baseline.literal) patch.literal_time_text = form.literal;
      if (task.recurrence && form.scope === 'occurrence') payload.occurrence_patch = patch;
      else {
        if (Object.keys(patch).length && form.temporal === 'undated') patch.literal_time_text = form.literal;
        payload.definition_patch = patch;
      }
      payload.audience_confirmed = form.space !== edit.baseline.space;
      if (form.status !== edit.baseline.status && occ) {
        payload.occurrence_action = { action: form.status === 'completed' ? 'complete' : 'reopen', expected_version: edit.occurrenceVersion };
      }
      await apply(payload);
    } catch (caught) { setLocalError((caught as Error).message); }
  };
  const quick = (action: string) => {
    const payload = basePayload();
    if (['complete', 'reopen', 'skip', 'cancel'].includes(action) && occ) payload.occurrence_action = { action, expected_version: occ.version };
    else payload.action = action;
    payload.expected_task_version = task.version;
    payload.expected_occurrence_version = occ?.version;
    void apply(payload);
  };
  const dateLabel = occ?.due_at ? localCardTime(occ.due_at, view.timezone).slice(0, 16).replace('T', ' ') : occ?.due_date || task.due_date || '暂不安排日期';
  const cycle = task.recurrence ? `每周${({ MO: '一', TU: '二', WE: '三', TH: '四', FR: '五', SA: '六', SU: '日' } as Record<string, string>)[task.recurrence.weekday || ''] || '内任选，周日截止'}` : '';
  const scopeOccurrence = !!task.recurrence && form.scope === 'occurrence';
  return <article className="interactive-card task-chat-card" aria-label={`${task.temporal_type === 'timed' ? '日程' : '备忘'}卡片：${occ?.title_snapshot || task.title}`}>
    <div className="task-card-top"><span className="task-card-kind">{task.temporal_type === 'timed' ? <CalendarDays size={15} /> : <StickyNote size={15} />}
      {task.space_type === 'household' ? '家庭' : '个人'}{task.temporal_type === 'timed' ? '日程' : '备忘'}</span>
      <span className={`task-card-state ${view.time_state === 'expired' ? 'is-expired' : ''}`}>{timeStates[view.time_state] || view.time_state}{view.read_only ? ' · 只读' : ''}</span></div>
    <h3 className="task-card-title">{occ?.title_snapshot || task.title}</h3>
    <dl className="task-card-facts">
      <dt>时间</dt><dd>{dateLabel}{cycle && <><br />{cycle}</>}</dd>
      <dt>负责人</dt><dd>{(occ?.assignee_ids || task.assignee_ids).length ? (occ?.assignee_ids || task.assignee_ids).map(id => <span className="task-card-person" key={id}>@{name(id)}</span>) : task.actionable ? '待认领' : '信息记录'}</dd>
      <dt>完成情况</dt><dd>{statuses[occ?.status || 'information']}{occ && occ.assignee_ids.length > 1 && ` · ${Object.values(occ.member_progress).filter(p => p.status === 'completed').length}/${occ.assignee_ids.length} 人完成`}</dd>
    </dl>
    <p className="task-card-note">已保存 · {task.space_type === 'household' ? '全家可见' : task.assignee_ids.some(id => id !== task.created_by) ? '你和被指派成员可见' : '个人可见'} · {view.timezone}</p>
    {view.read_only_reason && <p className="task-card-note">{view.read_only_reason === 'expired' && actions.includes('complete')
      ? '该事项已过期，仍可补标本人完成；其他内容仅供查看。'
      : reasons[view.read_only_reason] || '当前仅供查看。'}</p>}
    {edit.editing && !view.read_only && <div className="task-card-editor">
      {task.recurrence && <label>修改范围<select aria-label="修改范围" value={form.scope} disabled={locked || dirty} onChange={e => {
        const next = formFor(view, e.target.value);
        setEdit(current => ({ ...current, form: next, baseline: next }));
      }}><option value="occurrence">仅本期标题与时间</option><option value="future">从下周起的系列定义</option></select>{dirty && <span>切换范围前请先保存或放弃修改。</span>}</label>}
      {task.recurrence && form.scope === 'future' && <p className="task-card-note">系列定义从 {view.effective_on} 起生效；本期完成情况仍对应当前卡片。</p>}
      <label>标题<input value={form.title} maxLength={500} disabled={fieldLocked} onChange={e => update('title', e.target.value)} /></label>
      <div className="task-card-pair"><label>事项类型<select aria-label="事项类型" value={form.temporal} disabled={fieldLocked || scopeOccurrence} onChange={e => update('temporal', e.target.value)}><option value="timed">日程</option><option value="undated">备忘</option></select></label>
        <label>空间<select aria-label="空间" value={form.space} disabled={fieldLocked || scopeOccurrence} onChange={e => update('space', e.target.value)}><option value="personal">个人</option><option value="household">家庭</option></select></label></div>
      {form.space !== edit.baseline.space && <p className="task-card-note">保存后将改为{form.space === 'household' ? '全家可见' : '个人及被指派成员可见'}。</p>}
      {form.temporal === 'timed' ? <><div className="task-card-pair"><label>日期<input type="date" value={form.day} disabled={fieldLocked} onChange={e => update('day', e.target.value)} /></label>
        <label>时间（可选）<input type="time" value={form.time} disabled={fieldLocked} onChange={e => update('time', e.target.value)} /></label></div>
        {form.day && form.day < view.server_now.slice(0, 10) && <p className="task-card-note">该日期已过去，保存后将无法修改事项内容，未完成时仍可补标完成。</p>}
        {!scopeOccurrence && <div className="task-card-pair"><label>重复<select aria-label="重复" value={form.weekly ? 'weekly' : 'once'} disabled={fieldLocked} onChange={e => update('weekly', e.target.value === 'weekly')}><option value="once">单次</option><option value="weekly">每周</option></select></label>
          {form.weekly && <label>每周安排<select aria-label="每周安排" value={form.weekday} disabled={fieldLocked} onChange={e => update('weekday', e.target.value)}><option value="">周内任选，周日截止</option>{['一', '二', '三', '四', '五', '六', '日'].map((day, i) => <option key={day} value={['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'][i]}>周{day}</option>)}</select></label>}</div>}</>
        : <>{edit.baseline.temporal === 'timed' && <p className="task-card-note">转为备忘后将清除日期、时间和周期。</p>}
          {hasTimeText(form.title + form.description) && <label><input type="checkbox" checked={form.literal} disabled={fieldLocked} onChange={e => update('literal', e.target.checked)} />保留时间文字，仅作为备忘内容</label>}</>}
      <MemberPicker members={view.members} selected={form.members} disabled={fieldLocked || scopeOccurrence} onChange={value => update('members', value)} />
      {form.members.length > 1 && <label>多人完成规则<select aria-label="多人完成规则" value={form.completion} disabled={fieldLocked || scopeOccurrence} onChange={e => update('completion', e.target.value)}><option value="all">每人都需完成</option><option value="any">任一人完成即可</option></select></label>}
      {occ && (actions.includes('complete') || actions.includes('reopen')) && <label>我的完成情况<select aria-label="我的完成情况" value={form.status} disabled={locked} onChange={e => update('status', e.target.value)}><option value="open">未完成</option><option value="completed">已完成</option></select></label>}
      {!scopeOccurrence && <label>备注<textarea value={form.description} disabled={fieldLocked} onChange={e => update('description', e.target.value)} /></label>}
      {conflict && <div className="task-card-alert" role="alert">事项已有新版本，未覆盖你的修改。当前服务端标题为“{serverForm.title}”，日期为 {serverForm.day || '无日期'}。<br /><button type="button" onClick={rebase} disabled={busy}>保留我的修改，按最新版本重新核对</button></div>}
    </div>}
    {(error || localError) && <p className="task-card-error" role="alert">{error || localError}</p>}
    {verifying && <p className="task-card-note" role="status">正在核实时效和最新状态，暂不能保存。</p>}
    {view.read_only && dirty && <details><summary>查看未保存的修改</summary><pre>{form.title}{'\n'}{form.day} {form.time}{'\n'}{form.description}</pre></details>}
    {(actions.length > 0 || uncertain || dirty) && <div className="task-card-actions">
      {uncertain ? <button className="card-primary" type="button" disabled={busy} onClick={retry}>核实并重试</button> : edit.editing && !view.read_only ? <>
        <button className="card-primary" type="button" disabled={!dirty || locked || conflict} onClick={() => void save()}>{busy ? '正在保存…' : '保存修改'}</button>
        <button type="button" disabled={busy} onClick={() => { forgetCardEdit(editKey); setEdit({ form: serverForm, baseline: serverForm, taskVersion: task.version, occurrenceVersion: occ?.version || 0, editing: false }); setLocalError(''); }}>放弃修改</button>
        {dirty && <span className="task-card-dirty">有未保存的修改</span>}
      </> : <>
        {canEdit && <button type="button" onClick={() => setEdit(e => ({ ...e, editing: true }))} disabled={locked}>调整事项</button>}
        {['complete', 'reopen', 'claim', 'resume'].filter(a => actions.includes(a)).map(a => <button type="button" key={a} disabled={locked} onClick={() => quick(a)}>{({ complete: '标记本人完成', reopen: '撤销本人完成', claim: '认领事项', resume: '继续系列' } as Record<string, string>)[a]}</button>)}
        {actions.some(a => ['archive', 'pause', 'skip', 'cancel'].includes(a)) && <details className="task-card-more"><summary>更多操作</summary>{['archive', 'pause', 'skip', 'cancel'].filter(a => actions.includes(a)).map(a => <button type="button" key={a} disabled={locked} onClick={() => quick(a)}>{({ archive: '归档事项', pause: '暂停系列', skip: '跳过本期', cancel: '取消本期' } as Record<string, string>)[a]}</button>)}</details>}
      </>}
      {verifying && <button type="button" onClick={refresh}>重新核实</button>}
    </div>}
    {view.additional_cards?.map(ref => <InteractiveCardHost key={ref.card_id} reference={ref} context={context} />)}
  </article>;
}

function MemberPicker({ members, selected, onChange, disabled }: { members: TaskCardView['members']; selected: string[]; onChange: (ids: string[]) => void; disabled: boolean }) {
  const [query, setQuery] = useState('');
  const candidates = members.filter(m => m.status === 'active' || selected.includes(m.member_id));
  const search = query.trim().toLocaleLowerCase();
  return <fieldset className="task-card-members" disabled={disabled}><legend><UsersRound size={13} aria-hidden="true" /> 负责人（可多选）</legend>
    {candidates.length > 6 && <input type="search" aria-label="搜索负责人" placeholder="搜索家人" value={query} onChange={e => setQuery(e.target.value)} />}
    {candidates.filter(m => !search || selected.includes(m.member_id) || [m.display_name, ...(m.aliases || [])].some(value => value.toLocaleLowerCase().includes(search))).map(m => <label key={m.member_id}><input type="checkbox" checked={selected.includes(m.member_id)} disabled={disabled || (m.status !== 'active' && !selected.includes(m.member_id))}
      onChange={e => onChange(e.target.checked ? [...selected, m.member_id] : selected.filter(id => id !== m.member_id))} />{m.display_name}{candidates.filter(other => other.display_name === m.display_name).length > 1 ? `（${m.aliases?.[0] || m.member_id}）` : ''}{m.status !== 'active' ? '（已停用）' : ''}</label>)}
  </fieldset>;
}

interface DraftEdit { items: DraftTaskItem[]; temporal: string; space: string; members: string[]; literal: boolean; completion: string; version: number }
function DraftCard({ view, editKey, submit, busy, verifying, uncertain, error, retry, refresh }: CardRenderProps<TaskCardView, TaskCardAction>) {
  const draft = view.draft!;
  const previous = readCardEdit<DraftEdit>(editKey);
  const initialTemporal = draft.invocation?.temporal_type || (draft.items.some(i => i.due_date || i.due_at || i.recurrence) ? 'timed' : 'undated');
  const [items, setItems] = useState<DraftTaskItem[]>(previous?.items || draft.items);
  const [temporal, setTemporal] = useState(previous?.temporal || initialTemporal);
  const [space, setSpace] = useState(previous?.space || draft.invocation?.space_type || 'personal');
  const [members, setMembers] = useState(previous?.members || draft.invocation?.mentions?.map(m => m.member_id) || []);
  const [literal, setLiteral] = useState(previous?.literal ?? draft.invocation?.literal_time_text ?? false);
  const [completion, setCompletion] = useState(previous?.completion || draft.invocation?.completion_mode || 'all');
  const [version, setVersion] = useState(previous?.version || draft.version);
  const [localError, setLocalError] = useState('');
  const locked = busy || verifying || uncertain || view.read_only;
  const conflict = version !== draft.version;
  const dirty = !equal(items, draft.items) || temporal !== initialTemporal || space !== (draft.invocation?.space_type || 'personal')
    || !equal(members, draft.invocation?.mentions?.map(m => m.member_id) || [])
    || literal !== (draft.invocation?.literal_time_text || false) || completion !== (draft.invocation?.completion_mode || 'all');
  useEffect(() => { writeCardEdit(editKey, { items, temporal, space, members, literal, completion, version }); }, [items, temporal, space, members, literal, completion, version, editKey]);
  useEffect(() => {
    if (!dirty) return;
    const leave = (event: Event) => { if (isImmediateUpdate()) return; event.preventDefault(); event.returnValue = true; };
    window.addEventListener('beforeunload', leave);
    return () => window.removeEventListener('beforeunload', leave);
  }, [dirty]);
  const updateItem = (i: number, patch: Partial<DraftTaskItem>) => setItems(current => current.map((item, index) => index === i ? { ...item, ...patch } : item));
  const updateTiming = (i: number, day: string, time: string) => {
    try {
      updateItem(i, { due_date: day || null, due_at: cardTimestamp(day, time, view.timezone) });
      setLocalError('');
    } catch (caught) { setLocalError((caught as Error).message); }
  };
  const create = async () => {
    try {
      const cleaned = items.map(item => {
        if (!item.title.trim()) throw new Error('请填写事项标题。');
        if (temporal === 'timed' && !item.due_date && !item.due_at && !item.recurrence) throw new Error('请补充日程日期。');
        return temporal === 'undated' ? { title: item.title, description: item.description || '' } : item;
      });
      await submit({ target: { resource: view.resource }, expected_version: version, items: cleaned,
        space_type: space, temporal_type: temporal, assignee_ids: members, completion_mode: completion, literal_time_text: literal });
      forgetCardEdit(editKey);
    } catch (caught) { setLocalError((caught as Error).message); }
  };
  return <article className="interactive-card task-chat-card" aria-label="待补充事项卡片">
    <div className="task-card-top"><span className="task-card-kind"><StickyNote size={15} /> 事项草稿</span><span className="task-card-state">{view.read_only ? '已过期 · 只读' : '尚未创建'}</span></div>
    <h3 className="task-card-title">补充后即可保存</h3>
    <div className="task-card-editor">
      <div className="task-card-pair"><label>事项类型<select aria-label="事项类型" value={temporal} disabled={locked} onChange={e => setTemporal(e.target.value)}><option value="timed">日程</option><option value="undated">备忘</option></select></label>
        <label>空间<select aria-label="空间" value={space} disabled={locked} onChange={e => setSpace(e.target.value)}><option value="personal">个人</option><option value="household">家庭</option></select></label></div>
      {items.map((item, i) => <div className="task-card-draft-item" key={i}>
        <label>{items.length > 1 ? `事项 ${i + 1} 标题` : '标题'}<input value={item.title} maxLength={500} disabled={locked} onChange={e => updateItem(i, { title: e.target.value })} /></label>
        {temporal === 'timed' && <div className="task-card-pair"><label>日期<input type="date" value={item.due_date || localCardTime(item.due_at, view.timezone).slice(0, 10)} disabled={locked} onChange={e => {
          const day = e.target.value; const time = localCardTime(item.due_at, view.timezone).slice(11, 16);
          updateTiming(i, day, time);
        }} /></label><label>时间（可选）<input type="time" value={localCardTime(item.due_at, view.timezone).slice(11, 16)} disabled={locked} onChange={e => {
          const day = item.due_date || localCardTime(item.due_at, view.timezone).slice(0, 10);
          if (!day && e.target.value) { setLocalError('请先选择日期。'); return; }
          updateTiming(i, day, e.target.value);
        }} /></label></div>}
      </div>)}
      <MemberPicker members={view.members} selected={members} disabled={locked} onChange={setMembers} />
      {members.length > 1 && <label>多人完成规则<select aria-label="多人完成规则" value={completion} disabled={locked} onChange={e => setCompletion(e.target.value)}><option value="all">每人都需完成</option><option value="any">任一人完成即可</option></select></label>}
      {temporal === 'undated' && hasTimeText(items.map(i => i.title + (i.description || '')).join(' ')) && <label><input type="checkbox" checked={literal} disabled={locked} onChange={e => setLiteral(e.target.checked)} />保留时间文字，仅作为备忘内容</label>}
      {conflict && <div className="task-card-alert" role="alert">草稿已有新版本，当前内容为“{draft.items.map(item => item.title).join('、')}”。你的输入仍保留。<button type="button" disabled={locked} onClick={() => setVersion(draft.version)}>已核对，按当前版本保存我的修改</button></div>}
    </div>
    {(error || localError) && <p className="task-card-error" role="alert">{error || localError}</p>}
    <p className="task-card-note">{view.read_only ? '这份草稿已失效，请重新发起记录。' : `尚未写入事项清单 · ${view.timezone}`}</p>
    {!view.read_only && <div className="task-card-actions">{uncertain ? <button type="button" className="card-primary" disabled={busy} onClick={retry}>核实并重试</button> : <button type="button" className="card-primary" disabled={locked || conflict} onClick={() => void create()}>{busy ? '正在创建…' : '创建事项'}</button>}
      {verifying && <button type="button" onClick={refresh}>重新核实</button>}</div>}
  </article>;
}
