import { useState } from 'react';
import type { ActivityData, ActivityKind } from '../../api/familyActivities';
import { activityTimeISO, localActivityTime } from './activityTime';

export function ActivityFields({ value, onChange, kind, timezone, editable, disabled }: {
  value: ActivityData; onChange: (value: ActivityData) => void; kind: ActivityKind; timezone: string; editable: string[]; disabled: boolean;
}) {
  const [timeError, setTimeError] = useState('');
  const patch = (change: Partial<ActivityData>) => onChange({ ...value, ...change });
  const locked = (key: string) => disabled || !editable.includes(key);
  const setTime = (key: 'participation_deadline_at' | 'expires_at', input: string) => {
    try { patch({ [key]: activityTimeISO(input, timezone), [key === 'expires_at' ? 'retention_duration_hours' : 'participation_duration_hours']: null }); setTimeError(''); }
    catch (error) { setTimeError((error as Error).message); }
  };
  return <fieldset className="board-fields activity-fields" disabled={disabled}>
    <p className="board-card-meta">发布到家庭留言板，当前家庭所有有效成员可查看、实名参与。</p>
    <label>标题<input maxLength={120} value={value.title} disabled={locked('title')} onChange={e => patch({ title: e.target.value })} /></label>
    <label>说明<textarea rows={3} maxLength={5000} value={value.description} disabled={locked('description')} onChange={e => patch({ description: e.target.value })} /></label>
    {kind === 'poll' ? <>
      <div className="activity-options"><strong>投票选项（至少两项）</strong>{value.options.map((option, index) => <div className="activity-option-edit" key={option.id}>
        <input aria-label={`选项 ${index + 1}`} maxLength={300} placeholder={`选项 ${index + 1}`} value={option.text} disabled={locked('options')} onChange={e => patch({ options: value.options.map(o => o.id === option.id ? { ...o, text: e.target.value } : o) })} />
        <button type="button" aria-label={`移除选项 ${index + 1}`} disabled={locked('options')} onClick={() => patch({ options: value.options.filter(o => o.id !== option.id) })}>移除</button>
      </div>)}<button type="button" disabled={locked('options') || value.options.length >= 50} onClick={() => patch({ options: [...value.options, { id: window.crypto.randomUUID(), text: '' }] })}>添加选项</button></div>
      <label className="activity-check"><input type="checkbox" checked={value.multiple} disabled={locked('multiple')} onChange={e => patch({ multiple: e.target.checked, min_choices: 1, max_choices: e.target.checked ? Math.max(1, value.options.length) : 1 })} />允许多选</label>
      {value.multiple && <div className="activity-time-grid"><label>至少选择<input type="number" min={1} max={50} disabled={locked('min_choices')} value={value.min_choices} onChange={e => patch({ min_choices: Number(e.target.value) })} /></label><label>最多选择<input type="number" min={1} max={50} disabled={locked('max_choices')} value={value.max_choices} onChange={e => patch({ max_choices: Number(e.target.value) })} /></label></div>}
      <label className="activity-check"><input type="checkbox" checked={value.allow_change} disabled={locked('allow_change')} onChange={e => patch({ allow_change: e.target.checked })} />结束前允许修改或撤回本人选票</label>
      {!editable.includes('options') && <p className="board-card-meta">已有参与记录，题目和投票规则已冻结。</p>}
    </> : <>
      <label>接龙名额（按成员数，留空不限）<input type="number" min={1} max={100000} value={value.capacity ?? ''} disabled={locked('capacity')} onChange={e => patch({ capacity: e.target.value ? Number(e.target.value) : null })} /></label>
      <p className="board-card-meta">默认填写一条接龙内容；可添加自定义字段。每名成员一条，人数等填写值不额外占名额。</p>
      {value.fields.map((field, index) => <div className="activity-custom-field" key={field.id}>
        <input aria-label={`字段名称 ${index + 1}`} value={field.label} maxLength={120} disabled={locked('fields')} onChange={e => patch({ fields: value.fields.map(f => f.id === field.id ? { ...f, label: e.target.value } : f) })} />
        <select aria-label={`字段类型 ${index + 1}`} value={field.type} disabled={locked('fields')} onChange={e => patch({ fields: value.fields.map(f => f.id === field.id ? { ...f, type: e.target.value as 'text' | 'number' } : f) })}><option value="text">文字</option><option value="number">数字</option></select>
        <label className="activity-check"><input type="checkbox" checked={field.required} disabled={locked('fields')} onChange={e => patch({ fields: value.fields.map(f => f.id === field.id ? { ...f, required: e.target.checked } : f) })} />必填</label>
        <button type="button" disabled={locked('fields')} onClick={() => patch({ fields: value.fields.filter(f => f.id !== field.id) })}>移除</button>
      </div>)}<button type="button" disabled={locked('fields') || value.fields.length >= 12} onClick={() => patch({ fields: [...value.fields, { id: 'field_' + window.crypto.randomUUID(), label: '', type: 'text', required: true }] })}>添加填写字段</button>
    </>}
    <div className="activity-time-grid">{(['participation_deadline_at', 'expires_at'] as const).map(key => <label key={key}>{key === 'expires_at' ? '存在截止（到点自动销毁）' : '参与截止（到点结束）'}
      <input type="datetime-local" disabled={locked(key)} value={localActivityTime(value[key], timezone)} onChange={e => setTime(key, e.target.value)} />
      <span className="board-card-meta">{value[key] ? timezone : key === 'expires_at' ? '未设置：长期保留' : '未设置：不设参与截止'}</span>
      {value[key] && <button type="button" disabled={locked(key)} onClick={() => setTime(key, '')}>清除时间</button>}
    </label>)}</div>
    {timeError && <p role="alert">{timeError}</p>}
    {value.expires_at && value.expires_at === value.participation_deadline_at && <p>参与截止即销毁，结束后无法查看结果。</p>}
    {(value.participation_duration_hours || value.retention_duration_hours) && <p>从发布成功起算：参与 {value.participation_duration_hours ?? '不限制'} 小时；保留 {value.retention_duration_hours ?? '不限制'} 小时。选择具体时间可替换。</p>}
    <label className="activity-check"><input type="checkbox" checked={value.auto_close} disabled={locked('auto_close')} onChange={e => patch({ auto_close: e.target.checked })} />全员完成后自动结束（包含创建者本人）</label>
    <label className="activity-check"><input type="checkbox" checked={value.notify_creator} disabled={locked('notify_creator')} onChange={e => patch({ notify_creator: e.target.checked })} />截止或提前完成时通知我</label>
    <p className="board-card-meta">结束后结果只读；存在截止会销毁活动、选票与接龙内容。已发出的聊天原文由聊天单独管理。</p>
  </fieldset>;
}
