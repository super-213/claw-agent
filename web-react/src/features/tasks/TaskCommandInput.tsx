import { ArrowDown, ArrowUp, CalendarDays, CalendarRange, Check, ChevronDown, CornerDownLeft, NotebookPen, Search, SlidersHorizontal, StickyNote, UserRound, UsersRound, X } from 'lucide-react';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { commandFromText, invocationFor, taskCommands, type FamilyMember, type TaskCommand, type TaskInvocation, type TaskMention } from '../../api/tasks';
import { mentionBoundary, validMentions } from './taskSyntax';
import './task-command-input.css';

const commandDetails = {
  '日程': { icon: CalendarDays, description: '安排有时间的事项，向指定成员交代' },
  '备忘': { icon: StickyNote, description: '记下待办或信息，暂不安排时间' },
  '家庭日程': { icon: CalendarRange, description: '安排全家可见的日程，共同参与' },
  '家庭备忘': { icon: NotebookPen, description: '把待办或信息放进家庭共享空间' },
};

type MenuBindings = {
  handleKeyDown: (key: string) => boolean;
  menuId: string | undefined;
  activeOptionId: string | undefined;
};

export function TaskCommandInput({ text, onChange, members, mentions, onMentions, invocation, onInvocation, disabled, onFocusInput, children }: {
  text: string; onChange: (text: string) => void; members: FamilyMember[];
  mentions: TaskMention[]; onMentions: (mentions: TaskMention[]) => void;
  invocation: TaskInvocation | null; onInvocation: (value: TaskInvocation | null) => void;
  disabled?: boolean; onFocusInput: () => void;
  children: (bindings: MenuBindings) => ReactNode;
}) {
  const id = useId();
  const shellRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState({ text, index: 0 });
  const [dismissedText, setDismissedText] = useState<string | null>(null);
  const [panel, setPanel] = useState<{ text: string; kind: 'commands' | 'options' } | null>(null);
  useEffect(() => {
    setDismissedText(null);
    setPanel(null);
  }, [text]);
  useEffect(() => {
    const dismissOutside = (event: globalThis.PointerEvent) => {
      if (event.target instanceof Node && !shellRef.current?.contains(event.target)) {
        setDismissedText(text); setPanel(null);
      }
    };
    document.addEventListener('pointerdown', dismissOutside);
    return () => document.removeEventListener('pointerdown', dismissOutside);
  }, [text]);
  const command = commandFromText(text);
  const selectedMentions = validMentions(text, mentions);
  const manualPanel = panel?.text === text ? panel.kind : null;
  const prefixMenu = text.startsWith('/ ') && !command && /^\/ [^\n]*$/.test(text);
  const trailingTag = command ? /@ ([^\s@]*)$/.exec(text) : null;
  const tagMatch = trailingTag && mentionBoundary(text, trailingTag.index) ? trailingTag : null;
  const commandMenu = manualPanel === 'commands' || prefixMenu;
  const menuOpen = !disabled && dismissedText !== text && (commandMenu || !!tagMatch);
  const choices = commandMenu ? taskCommands.filter(c => manualPanel === 'commands' || c.includes(text.slice(2))) : [];
  const memberChoices = tagMatch && !commandMenu ? members.filter(m => m.status === 'active' && !selectedMentions.some(t => t.member_id === m.member_id)
    && (m.display_name.includes(tagMatch[1]) || m.aliases.some(a => a.includes(tagMatch[1])))) : [];
  const count = commandMenu ? choices.length : memberChoices.length;
  const highlight = selection.text === text ? selection.index % Math.max(count, 1) : 0;
  const optionId = (index: number) => `${id}-option-${index}`;
  const close = () => { setDismissedText(text); setPanel(null); };
  const selectCommand = (next: TaskCommand) => {
    const oldPrefix = command ? `/ ${command} ` : text;
    const nextText = `/ ${next} ${command ? text.slice(oldPrefix.length) : ''}`;
    const delta = `/ ${next} `.length - oldPrefix.length;
    const selected = command ? selectedMentions.map(m => ({ ...m, start: m.start + delta, end: m.end + delta })) : [];
    onChange(nextText);
    onMentions(selected);
    onInvocation(invocationFor(next, selected));
    setPanel(null);
    onFocusInput();
  };
  const selectMember = (member: FamilyMember) => {
    if (!tagMatch) return;
    const start = tagMatch.index;
    const label = member.display_name;
    const next = text.slice(0, start) + `@ ${label} `;
    const selected = [...selectedMentions, { member_id: member.member_id, label, start, end: start + label.length + 2 }];
    onChange(next);
    onMentions(selected);
    onInvocation({ ...(invocation || invocationFor(command!)), mentions: selected });
    onFocusInput();
  };
  const handleKeyDown = (key: string) => {
    if (!menuOpen) return false;
    if (key === 'Escape') { close(); return true; }
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      const index = (highlight + (key === 'ArrowDown' ? 1 : Math.max(count, 1) - 1)) % Math.max(count, 1);
      setSelection({ text, index });
      listRef.current?.querySelector<HTMLElement>(`[data-index="${index}"]`)?.scrollIntoView?.({ block: 'nearest' });
      return true;
    }
    if (key === 'Enter') {
      if (count) {
        if (commandMenu) selectCommand(choices[highlight]); else selectMember(memberChoices[highlight]);
      }
      return true;
    }
    return false;
  };
  const CommandIcon = command ? commandDetails[command].icon : CalendarDays;
  const hasTimeText = command?.endsWith('备忘') && /今天|明天|后天|每周|每月|每天|\d{4}-\d{2}-\d{2}/.test(text);

  return <div className="task-composer-shell" ref={shellRef}>
    {menuOpen && <div className="task-invocation-picker" onMouseDown={e => e.preventDefault()}>
      <div className="task-picker-heading">
        {commandMenu ? <CalendarDays size={14} /> : <UsersRound size={14} />}
        <span>{commandMenu ? '选择事项类型' : '指定负责人'}</span>
        <kbd>{commandMenu ? '/' : '@'}</kbd>
      </div>
      <div ref={listRef} id={id} role="listbox" aria-label={commandMenu ? '事项命令' : '选择家庭成员'} className="task-picker-list">
        {choices.map((c, i) => {
          const Icon = commandDetails[c].icon;
          return <button id={optionId(i)} data-index={i} role="option" aria-label={`/ ${c}`} aria-selected={i === highlight} tabIndex={-1} type="button" key={c} className="task-picker-option" onClick={() => selectCommand(c)}>
            <span className="task-picker-icon"><Icon size={15} /></span>
            <span className="task-picker-copy"><strong>/ {c}</strong><small>{commandDetails[c].description}</small></span>
            {i === highlight && <CornerDownLeft size={13} className="task-picker-return" />}
          </button>;
        })}
        {memberChoices.map((m, i) => <button id={optionId(i)} data-index={i} role="option" aria-label={m.display_name} aria-selected={i === highlight} tabIndex={-1} type="button" key={m.member_id} className="task-picker-option" onClick={() => selectMember(m)}>
          <span className="task-picker-icon"><UserRound size={15} /></span>
          <span className="task-picker-copy"><strong>{m.display_name}</strong><small>{m.aliases.length ? `也可以叫 ${m.aliases.join('、')}` : '家庭成员 · 参与这条事项'}</small></span>
          {i === highlight && <CornerDownLeft size={13} className="task-picker-return" />}
        </button>)}
        {!count && <div className="task-picker-empty"><Search size={17} /><span>{commandMenu ? '没有匹配的事项类型' : '没有可选的匹配成员'}</span></div>}
      </div>
      <div className="task-picker-footer" aria-hidden="true">
        <span><CornerDownLeft size={11} /> 选择</span><span><ArrowUp size={10} /><ArrowDown size={10} /> 浏览</span><span><kbd>esc</kbd> 关闭</span>
        {!commandMenu && <span className="task-picker-note">不发送通知</span>}
      </div>
    </div>}
    <div className="composer">
      {command && <div className="task-command-controls">
        <div className="task-input-tags">
          <button type="button" disabled={disabled} className="task-input-chip task-type-chip" aria-label="切换事项命令" aria-expanded={menuOpen && commandMenu} onClick={() => {
            if (manualPanel === 'commands' && menuOpen) { close(); onFocusInput(); return; }
            setPanel({ text, kind: 'commands' }); setDismissedText(null); setSelection({ text, index: taskCommands.indexOf(command) }); onFocusInput();
          }}><CommandIcon size={13} /><span>{command}</span><ChevronDown size={11} /></button>
          {selectedMentions.map(m => <button key={m.member_id} type="button" disabled={disabled} className="task-input-chip" aria-label={`移除负责人 ${m.label}`} onClick={() => {
            const end = m.end + (text[m.end] === ' ' ? 1 : 0);
            const next = text.slice(0, m.start) + text.slice(end);
            const remaining = selectedMentions.filter(v => v.member_id !== m.member_id).map(v => v.start > m.start ? { ...v, start: v.start - (end - m.start), end: v.end - (end - m.start) } : v);
            onChange(next); onMentions(remaining); onFocusInput();
          }}><UserRound size={12} /><span>{m.label}</span><X size={11} /></button>)}
          <span className="task-input-audience">{command.startsWith('家庭') ? '全家可见' : '仅相关成员可见'}</span>
          <button type="button" disabled={disabled} className="task-options-toggle" aria-label="事项选项" aria-expanded={manualPanel === 'options'} onClick={() => {
            setPanel(manualPanel === 'options' ? null : { text, kind: 'options' }); setDismissedText(text);
          }}><SlidersHorizontal size={13} /><span>选项</span></button>
        </div>
        {manualPanel === 'options' && <div className="task-input-options" onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); close(); onFocusInput(); } }}>
          <div className="task-options-heading"><strong>事项选项</strong><button type="button" aria-label="关闭事项选项" onClick={() => { setPanel(null); onFocusInput(); }}><X size={14} /></button></div>
          {command.endsWith('备忘') && <label className="task-option-check"><input type="checkbox" checked={invocation?.actionable === false}
            onChange={e => onInvocation({ ...(invocation || invocationFor(command)), actionable: !e.target.checked })} /><span>仅作信息记录<small>不需要标记完成</small></span></label>}
          <label className="task-option-rule">多人完成规则<select aria-label="多人完成规则" value={invocation?.completion_mode || 'all'}
            onChange={e => onInvocation({ ...(invocation || invocationFor(command)), completion_mode: e.target.value as 'all' | 'any' })}>
            <option value="all">每人都要完成</option><option value="any">任一人完成即可</option>
          </select></label>
        </div>}
        {hasTimeText && <div className="task-time-choice"><span>{invocation?.literal_time_text ? <Check size={12} /> : <CalendarDays size={12} />}{invocation?.literal_time_text ? '时间描述仅作文字保存' : '这条备忘包含时间描述'}</span>
          <button type="button" disabled={disabled} onClick={() => selectCommand(command.startsWith('家庭') ? '家庭日程' : '日程')}>转为日程</button>
          <label><input type="checkbox" disabled={disabled} checked={invocation?.literal_time_text || false}
            onChange={e => onInvocation({ ...(invocation || invocationFor(command)), literal_time_text: e.target.checked })} />仅作文字</label>
        </div>}
      </div>}
      {children({ handleKeyDown, menuId: menuOpen ? id : undefined, activeOptionId: menuOpen && count ? optionId(highlight) : undefined })}
    </div>
  </div>;
}
