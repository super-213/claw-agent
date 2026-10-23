import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { adminApi } from '../../api/admin';
import { invocationFor, requestId, tasksApi, type FamilyMember, type TaskCommand, type TaskDefinition, type TaskDetail, type TaskList, type TaskRow, type TaskSummary } from '../../api/tasks';
import type { User } from '../../api/types';
import { useAppStore } from '../../stores/appStore';
import './tasks.css';

const stateNames: Record<string, string> = { open: '未完成', completed: '已完成', skipped: '本期跳过', cancelled: '已取消', active: '进行中', paused: '已暂停', archived: '已归档' };
const weekdays = ['整周一次', '周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const codes = ['', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'];

export function TaskBoard() {
  const currentUser = useAppStore(s => s.currentUser);
  const [members, setMembers] = useState<FamilyMember[]>([]);
  const [actor, setActor] = useState<string | null>(null);
  const [space, setSpace] = useState('personal');
  const [temporal, setTemporal] = useState('undated');
  const [view, setView] = useState('mine');
  const [period, setPeriod] = useState('all');
  const [status, setStatus] = useState('open');
  const [lifecycle, setLifecycle] = useState('');
  const [memberFilter, setMemberFilter] = useState('');
  const [query, setQuery] = useState('');
  const [data, setData] = useState<TaskList | null>(null);
  const [summary, setSummary] = useState<TaskSummary | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [allRows, setAllRows] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [date, setDate] = useState('');
  const [weekly, setWeekly] = useState(false);
  const [weekday, setWeekday] = useState('');
  const [selectedMembers, setSelectedMembers] = useState<string[]>([]);
  const [mode, setMode] = useState<'all' | 'any'>('all');
  const [information, setInformation] = useState(false);
  const [literalTime, setLiteralTime] = useState(false);
  const [accounts, setAccounts] = useState<User[]>([]);
  const [bindAccount, setBindAccount] = useState('');
  const [bindName, setBindName] = useState('');
  const [bindAliases, setBindAliases] = useState('');
  const [memberEdit, setMemberEdit] = useState('');
  const [speakerAliases, setSpeakerAliases] = useState('{}');
  const [review, setReview] = useState<Record<string, { reasons: string[]; source: { title?: string } }> | null>(null);
  const generation = useRef(0);
  const submission = useRef<{ id: string; fingerprint: string } | null>(null);
  const nextCursor = useRef<string | null>(null);
  const name = (mid: string) => members.find(m => m.member_id === mid)?.display_name || mid;

  const filters = useCallback(() => ({ view: space === 'household' ? 'household' : view,
    ...(temporal !== 'information' ? { status } : {}),
    ...(temporal === 'information' ? { temporal_type: 'undated', actionable: 'false', status: '' } : { temporal_type: temporal, actionable: 'true' }),
    ...(memberFilter ? { assignee_id: memberFilter } : {}), ...(query ? { query } : {}), ...(lifecycle ? { lifecycle } : {}),
    ...(period === 'weekly' ? { recurring: 'true', current_only: 'true' } : {}),
  }), [space, view, temporal, status, memberFilter, query, period, lifecycle]);

  const load = useCallback(async (append = false) => {
    const revision = ++generation.current;
    setLoading(true);
    try {
      const listFilters: Record<string, string> = filters();
      const [memberData, totals] = await Promise.all([tasksApi.members(), tasksApi.summary({ view: space === 'household' ? 'household' : view })]);
      if (revision !== generation.current) return;
      setMembers(memberData.members); setActor(memberData.current_member_id);
      const today = totals.as_of.slice(0, 10);
      if (period === 'today' || period === 'tomorrow') {
        // Arithmetic on the server-provided local date, never the browser's current day.
        const day = new Date(`${today}T12:00:00Z`);
        if (period === 'tomorrow') day.setUTCDate(day.getUTCDate() + 1);
        listFilters.due_from = day.toISOString().slice(0, 10); listFilters.due_to = listFilters.due_from;
      }
      if (period === 'week') {
        const day = new Date(`${today}T12:00:00Z`);
        day.setUTCDate(day.getUTCDate() + (7 - day.getUTCDay()) % 7);
        listFilters.due_from = today; listFilters.due_to = day.toISOString().slice(0, 10);
      }
      const result = await tasksApi.list({ ...listFilters, ...(append && nextCursor.current ? { cursor: nextCursor.current } : {}) });
      if (revision !== generation.current) return;
      nextCursor.current = result.next_cursor;
      setSummary(totals); setData(previous => append && previous ? { ...result, items: [...previous.items, ...result.items] } : result); setError('');
    } catch (caught) {
      if (revision === generation.current) setError((caught as Error).message || '查询失败');
    } finally { if (revision === generation.current) setLoading(false); }
  }, [filters, space, view, period]);

  useEffect(() => {
    generation.current++; setData(null); setSummary(null); setDetail(null); setMembers([]); setActor(null);
    setSelectedMembers([]); submission.current = null;
    void load();
    const refresh = () => { if (document.visibilityState === 'visible') void load(); };
    const timer = window.setInterval(refresh, 60_000);
    window.addEventListener('focus', refresh); window.addEventListener('task_changed', refresh);
    document.addEventListener('visibilitychange', refresh);
    // A request generation counter intentionally changes on cleanup to discard stale account responses.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => { generation.current++; window.clearInterval(timer); window.removeEventListener('focus', refresh);
      window.removeEventListener('task_changed', refresh); document.removeEventListener('visibilitychange', refresh); };
  }, [load, currentUser?.id]);

  const run = async (action: () => Promise<unknown>) => {
    setSaving(true); setError('');
    try { await action(); await load(); window.dispatchEvent(new CustomEvent('task_changed')); }
    catch (caught) { setError((caught as Error).message); }
    finally { setSaving(false); }
  };
  const mutate = (row: TaskRow, action: string, occurrenceAction = false) => run(() => tasksApi.change(row.task.id, action,
    { expected_version: occurrenceAction ? row.occurrence!.version : row.task.version }, occurrenceAction ? row.occurrence!.id : undefined));
  const create = async (event: FormEvent) => {
    event.preventDefault();
    const command = `${space === 'household' ? '家庭' : ''}${temporal === 'timed' ? '日程' : '备忘'}` as TaskCommand;
    const invocation = { ...invocationFor(command), actionable: temporal !== 'information' && !information,
      completion_mode: mode, literal_time_text: literalTime,
      mentions: selectedMembers.map(member_id => ({ member_id, label: name(member_id), start: 0, end: 0 })) };
    const items = title.split(/[、\n]+/).filter(t => t.trim()).map(t => ({ title: t.trim(), space_type: invocation.space_type,
      temporal_type: invocation.temporal_type, actionable: invocation.actionable, completion_mode: mode,
      ...(temporal === 'timed' ? { due_date: date || undefined, starts_on: weekly && date ? date : undefined,
        recurrence: weekly ? { frequency: 'weekly', interval: 1, week_start: 'MO', weekday: weekday || null } : undefined } : {}),
    }));
    if (!items.length) return;
    const fingerprint = JSON.stringify({ items, invocation });
    if (submission.current?.fingerprint !== fingerprint) submission.current = { id: requestId(), fingerprint };
    await run(async () => { await tasksApi.create(items, invocation, submission.current!.id);
      submission.current = null; setTitle(''); setShowCreate(false); });
  };
  const openDetail = (task: TaskDefinition) => run(async () => setDetail(await tasksApi.get(task.id)));
  const bind = async (event: FormEvent) => {
    event.preventDefault();
    await run(async () => {
      await tasksApi.bindMember(memberEdit || `member_${bindAccount}`, { user_id: bindAccount, display_name: bindName,
        aliases: bindAliases.split(/[、,]/).map(s => s.trim()).filter(Boolean), speaker_aliases: JSON.parse(speakerAliases) });
      setMembers((await tasksApi.members()).members);
    });
  };
  const visible = (data?.items || []).filter(row => period !== 'overdue' || row.overdue);
  const rows = allRows ? visible : visible.slice(0, 6);

  return <section className="home-section task-board" id="reminders" aria-label="家庭事项清单">
    <div className="home-section-head"><div><h2>事项清单</h2><p>主动查询与处理 · 不发送通知</p></div>
      <button type="button" onClick={() => setShowCreate(!showCreate)}>记录事项</button></div>
    <div className="task-filter-bar">
      <label>空间<select value={space} onChange={e => setSpace(e.target.value)}><option value="personal">个人空间（含指派引用）</option><option value="household">家庭空间</option></select></label>
      <label>性质<select value={temporal} onChange={e => setTemporal(e.target.value)}><option value="timed">日程</option><option value="undated">备忘</option><option value="information">信息记录</option></select></label>
      {space === 'personal' && <label>视图<select value={view} onChange={e => setView(e.target.value)}><option value="mine">我的事项</option><option value="own">自己的</option><option value="assigned">指派给我的</option><option value="delegated">我交代的</option></select></label>}
      <label>时间<select value={period} onChange={e => setPeriod(e.target.value)}><option value="all">全部（含无日期）</option><option value="today">今天</option><option value="tomorrow">明天</option><option value="overdue">逾期</option><option value="week">本周</option><option value="weekly">周期事项本期</option></select></label>
      <label>状态<select value={status} onChange={e => setStatus(e.target.value)}><option value="open">未完成</option><option value="completed">已完成</option><option value="">全部状态</option><option value="cancelled">已取消</option></select></label>
      <label>系列状态<select value={lifecycle} onChange={e => setLifecycle(e.target.value)}><option value="">活跃及暂停</option><option value="active">活跃</option><option value="paused">已暂停</option><option value="archived">已归档 / 已停止</option></select></label>
      <label>负责人<select value={memberFilter} onChange={e => setMemberFilter(e.target.value)}><option value="">所有成员（含未认领）</option>{members.map(m => <option value={m.member_id} key={m.member_id}>{m.display_name}{m.status === 'active' ? '' : '（已停用）'}</option>)}</select></label>
      <label>搜索<input value={query} onChange={e => setQuery(e.target.value)} placeholder="事项标题" /></label>
    </div>
    <div className="task-counts" aria-live="polite">{summary && `今日 ${summary.counts.today} · 无日期 ${summary.counts.undated} · 逾期 ${summary.counts.overdue ?? '整理中'} · 未认领 ${summary.counts.unclaimed}`}</div>
    {error && <p className="task-error" role="alert">{error}<button type="button" onClick={() => void load()}>重试</button></p>}
    {loading && <p role="status">正在读取事项…</p>}
    {saving && <p role="status">正在保存…</p>}
    {data && !data.history_complete && <p role="status">历史整理中，历史总数暂不完整。<button type="button" onClick={() => void load()}>继续整理历史</button></p>}
    {showCreate && <form onSubmit={e => void create(e)} className="task-create-form">
      <label>事项（顿号或换行拆成多条）<textarea required aria-label="事项内容" value={title} onChange={e => { setTitle(e.target.value); submission.current = null; }} /></label>
      {temporal === 'timed' && <><label>执行日期 / 周期开始<input type="date" value={date} onChange={e => { setDate(e.target.value); submission.current = null; }} required={!weekly} /></label>
        <label><input type="checkbox" checked={weekly} onChange={e => setWeekly(e.target.checked)} />每周一次</label>
        {weekly && <select aria-label="每周执行日" value={weekday} onChange={e => setWeekday(e.target.value)}>{weekdays.map((day, i) => <option key={day} value={codes[i]}>{day}</option>)}</select>}</>}
      {temporal !== 'timed' && <><label><input type="checkbox" checked={information || temporal === 'information'} onChange={e => setInformation(e.target.checked)} />信息记录（仅编辑和归档）</label>
        <label><input type="checkbox" checked={literalTime} onChange={e => setLiteralTime(e.target.checked)} />时间表达仅作为文字保存</label></>}
      <fieldset><legend>指定成员（可多选）</legend>{members.filter(m => m.status === 'active').map(m => <label key={m.member_id}><input type="checkbox" checked={selectedMembers.includes(m.member_id)} onChange={e => setSelectedMembers(e.target.checked ? [...selectedMembers, m.member_id] : selectedMembers.filter(v => v !== m.member_id))} />{m.display_name}</label>)}</fieldset>
      <label>多人规则<select value={mode} onChange={e => setMode(e.target.value as 'all' | 'any')}><option value="all">每人都要完成</option><option value="any">任一人完成即可</option></select></label>
      <p>{space === 'household' ? '全家可见；未指定成员的待办等待认领。' : '交代者与指定成员可见；未指定成员默认由自己负责。'}</p>
      <button type="submit" disabled={saving}>保存{information || temporal === 'information' ? '信息' : '事项'}</button>
    </form>}
    <div className="home-list">{rows.map(row => {
      const { task, occurrence: occ } = row;
      const progress = Object.values(occ?.member_progress || {}).filter(p => p.status === 'completed').length;
      const mineDone = actor && occ?.member_progress[actor]?.status === 'completed';
      const responsible = actor && occ?.assignee_ids.includes(actor);
      return <article className="home-list-item task-row" key={occ?.id || task.id}>
        <div><button type="button" className="task-title" onClick={() => void openDetail(task)}>{occ?.title_snapshot || task.title}</button>
          <small>来源：{task.space_type === 'household' ? '家庭空间' : '个人空间'} · 交代者 {name(task.created_by)}</small>
          <small>{(occ?.assignee_ids || task.assignee_ids).map(name).join('、') || (task.actionable ? '待认领' : '信息记录')} · {occ?.due_date || '无日期'}{occ?.due_at ? ` ${occ.due_at}` : ''}{task.recurrence ? ' · 每周' : ''} · {stateNames[task.lifecycle]}</small>
          {occ && <small>{stateNames[occ.status]} · {occ.legacy_completion_unknown_actor ? '旧记录完成者未知' : `已完成 ${progress}/${occ.assignee_ids.length}`} · {occ.completion_mode === 'all' ? '每人完成' : '任一人完成'}{row.overdue ? ' · 已逾期' : ''}{occ.projected ? ' · 预览' : ''}</small>}
          {row.assignee_unavailable.length > 0 && <small>负责人已停用，请交代者重新分配</small>}
        </div>
        <div className="row-actions">
          {task.actionable && !task.assignee_ids.length && task.space_type === 'household' && <button type="button" disabled={saving} onClick={() => void mutate(row, 'claim')}>认领</button>}
          {responsible && occ && ['open', 'completed'].includes(occ.status) && <button type="button" disabled={saving} onClick={() => void mutate(row, mineDone || occ.legacy_completion_unknown_actor ? 'reopen' : 'complete', true)}>{mineDone || occ.legacy_completion_unknown_actor ? '撤销完成' : task.recurrence ? '完成本周' : '完成'}</button>}
          <button type="button" onClick={() => void openDetail(task)}>详情与历史</button>
        </div>
      </article>;
    })}</div>
    {!loading && !rows.length && !error && <p>暂无符合条件的事项。</p>}
    {!allRows && visible.length > 6 && <button type="button" onClick={() => setAllRows(true)}>查看全部</button>}
    {data?.next_cursor && <button type="button" onClick={() => void load(true)}>加载更多</button>}
    {detail && <TaskDetails key={detail.task.id} detail={detail} actor={actor} members={members} saving={saving}
      onClose={() => setDetail(null)} onSave={(action, patch, occ) => run(async () => {
        await tasksApi.change(detail.task.id, action, { expected_version: occ?.version || detail.task.version, patch }, occ?.id);
        setDetail(await tasksApi.get(detail.task.id));
      })} />}
    {currentUser?.role === 'admin' && <details className="task-admin"><summary onClick={() => void adminApi.users().then(r => setAccounts(r.users))}>家庭成员绑定与迁移核对（管理员）</summary>
      <p>只有显式绑定的有效账号才能使用家庭事项，不会自动授权全部账号。技术管理员仍可管理会话。</p>
      <form onSubmit={e => void bind(e)}>
        <label>现有成员<select value={memberEdit} onChange={e => {
          setMemberEdit(e.target.value); const m = members.find(v => v.member_id === e.target.value);
          if (m) { setBindAccount(m.user_id); setBindName(m.display_name); setBindAliases(m.aliases.join('、')); }
        }}><option value="">新增绑定</option>{members.map(m => <option key={m.member_id} value={m.member_id}>{m.display_name}</option>)}</select></label>
        <label>账号<select required value={bindAccount} onChange={e => { setBindAccount(e.target.value); const account = accounts.find(a => a.id === e.target.value); if (account) setBindName(account.display_name || account.username); }}><option value="">选择有效账号</option>{accounts.filter(a => a.status === 'active').map(a => <option key={a.id} value={a.id}>{a.display_name || a.username}</option>)}</select></label>
        <label>成员姓名<input required value={bindName} onChange={e => setBindName(e.target.value)} /></label>
        <label>通用称呼<input value={bindAliases} placeholder="以顿号分隔" onChange={e => setBindAliases(e.target.value)} /></label>
        <label>该成员的称呼映射（称呼 → 成员 ID）<input value={speakerAliases} onChange={e => setSpeakerAliases(e.target.value)} /></label>
        <button disabled={saving} type="submit">保存绑定</button>
      </form>
      <button type="button" onClick={() => void tasksApi.migrationReview().then(r => setReview(r.records))}>查看迁移待核对记录</button>
      {review && <ul>{Object.entries(review).map(([id, record]) => <li key={id}>{record.source.title || id}：{record.reasons.join('、')}</li>)}</ul>}
    </details>}
  </section>;
}

function TaskDetails({ detail, actor, members, saving, onClose, onSave }: {
  detail: TaskDetail; actor: string | null; members: FamilyMember[]; saving: boolean;
  onClose: () => void; onSave: (action: string, patch: Record<string, unknown>, occurrence?: TaskDetail['occurrences'][number]) => Promise<void>;
}) {
  const task = detail.task;
  const [title, setTitle] = useState(task.title);
  const [date, setDate] = useState(task.due_date || '');
  const [weekly, setWeekly] = useState(Boolean(task.recurrence));
  const [space, setSpace] = useState(task.space_type);
  const [temporal, setTemporal] = useState(task.temporal_type);
  const [assignees, setAssignees] = useState(task.assignee_ids);
  const [audience, setAudience] = useState(false);
  const [reason, setReason] = useState('');
  const [mode, setMode] = useState(task.completion_mode || 'all');
  const [weekday, setWeekday] = useState(task.recurrence?.weekday || '');
  const [editingOccurrence, setEditingOccurrence] = useState<TaskDetail['occurrences'][number] | null>(null);
  const [occurrenceDate, setOccurrenceDate] = useState('');
  const [occurrenceTitle, setOccurrenceTitle] = useState('');
  return <div className="task-details" role="region" aria-label="事项详情"><button type="button" onClick={onClose}>关闭详情</button>
    <h3>{task.title}</h3><p>{task.id} · {stateNames[task.lifecycle]} · 历史{detail.history_complete ? '已整理' : '整理中'}</p>
    {task.history_before_migration === 'unknown' && <p>迁移前的执行历史未知，未根据旧发送日志推断完成情况。</p>}
    {actor === task.created_by && <form onSubmit={e => { e.preventDefault(); void onSave('update', {
      title, due_date: temporal === 'timed' ? date || null : null, due_at: null,
      space_type: space, temporal_type: temporal, assignee_ids: assignees, completion_mode: mode, audience_confirmed: audience,
      recurrence: weekly && temporal === 'timed' ? { frequency: 'weekly', interval: 1, week_start: 'MO', weekday: weekday || null } : null,
      starts_on: weekly && temporal === 'timed' ? task.starts_on || date || null : null, scope: 'future', literal_time_text: true,
    }); }}>
      <label>标题<input required value={title} onChange={e => setTitle(e.target.value)} /></label>
      <label>空间<select value={space} onChange={e => setSpace(e.target.value as typeof space)}><option value="personal">个人</option><option value="household">家庭</option></select></label>
      {space !== task.space_type && <label><input type="checkbox" required checked={audience} onChange={e => setAudience(e.target.checked)} />确认可见范围变为{space === 'household' ? '全家可见' : '交代者与指定成员可见'}</label>}
      <label>性质<select value={temporal} onChange={e => setTemporal(e.target.value as typeof temporal)}><option value="timed">日程</option><option value="undated">备忘</option></select></label>
      {temporal === 'timed' && <><input aria-label="修改执行日期" type="date" value={date} onChange={e => setDate(e.target.value)} /><label><input type="checkbox" checked={weekly} onChange={e => setWeekly(e.target.checked)} />每周重复（未来周期生效）</label></>}
      {weekly && temporal === 'timed' && <label>每周执行日<select value={weekday} onChange={e => setWeekday(e.target.value)}>{weekdays.map((day, i) => <option value={codes[i]} key={day}>{day}</option>)}</select></label>}
      {task.actionable && <label>完成规则<select value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="all">每人都要完成</option><option value="any">任一人完成即可</option></select></label>}
      {task.actionable && <fieldset><legend>负责人（周期事项从下期生效）</legend>{members.filter(m => m.status === 'active').map(m => <label key={m.member_id}><input type="checkbox" checked={assignees.includes(m.member_id)} onChange={e => setAssignees(e.target.checked ? [...assignees, m.member_id] : assignees.filter(v => v !== m.member_id))} />{m.display_name}</label>)}</fieldset>}
      <button type="submit" disabled={saving}>保存修改</button>
    </form>}
    <div className="row-actions">{actor === task.created_by && <>
      {task.recurrence && task.lifecycle !== 'archived' && <button type="button" disabled={saving} onClick={() => void onSave(task.lifecycle === 'paused' ? 'resume' : 'pause', {})}>{task.lifecycle === 'paused' ? '恢复系列' : '暂停系列'}</button>}
      {task.lifecycle !== 'archived' && <button type="button" disabled={saving} onClick={() => void onSave('archive', { reason: '交代者归档或停止' })}>{task.recurrence ? '停止整个系列' : '归档'}</button>}
    </>}</div>
    {task.recurrence && actor && task.assignee_ids.includes(actor) && task.lifecycle !== 'archived' && <div>
      <label>暂停自己后续参与的原因<input value={reason} onChange={e => setReason(e.target.value)} /></label>
      <button type="button" disabled={saving || !reason.trim()} onClick={() => void onSave('leave', { reason })}>从下期暂停自己的参与</button>
    </div>}
    {editingOccurrence && actor === task.created_by && <form onSubmit={e => { e.preventDefault(); void onSave('update', { title: occurrenceTitle, due_date: occurrenceDate || null, due_at: null }, editingOccurrence).then(() => setEditingOccurrence(null)); }}>
      <label>仅修改本期内容<input required value={occurrenceTitle} onChange={e => setOccurrenceTitle(e.target.value)} /></label>
      {task.temporal_type === 'timed' && <label>仅修改本期日期<input type="date" required value={occurrenceDate} onChange={e => setOccurrenceDate(e.target.value)} /></label>}
      <button type="submit" disabled={saving}>保存本期</button>
    </form>}
    <h4>各期历史</h4><ul>{detail.occurrences.map(o => <li key={o.id}>{o.due_date || '无日期'} · {o.title_snapshot} · {stateNames[o.status]}
      {actor === task.created_by && o.status === 'open' && <><button type="button" disabled={saving} onClick={() => { setEditingOccurrence(o); setOccurrenceDate(o.due_date || ''); setOccurrenceTitle(o.title_snapshot); }}>修改本期</button><button type="button" disabled={saving} onClick={() => void onSave('skip', {}, o)}>跳过本期</button><button type="button" disabled={saving} onClick={() => void onSave('cancel', {}, o)}>取消本期</button></>}
    </li>)}</ul>
    {task.recurrence && <><h4>下一期预览</h4><ul>{detail.preview.map(o => <li key={o.id}>{o.due_date} · {o.title_snapshot}（预览）</li>)}</ul></>}
  </div>;
}
