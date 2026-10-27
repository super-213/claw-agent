import { useId, useState, type ReactNode } from 'react';
import type { FamilyMember } from '../../api/tasks';
import { mentionBoundary } from '../tasks/taskSyntax';

export function BoardMentionInput({ text, onChange, members, disabled, children }: {
  text: string; onChange: (text: string) => void; members: FamilyMember[]; disabled: boolean;
  children: (binding: { handleBoardKey: (key: string) => boolean; menuId?: string; activeOptionId?: string }) => ReactNode;
}) {
  const id = useId();
  const [index, setIndex] = useState(0);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const match = !text.startsWith('/ ') ? /@ ([^@\n]*)$/.exec(text) : null;
  const open = !disabled && dismissed !== text && match && mentionBoundary(text, match.index) && (text.trimStart().startsWith('@ ') || /便[笺签]|留言板/.test(text));
  const options = open ? [{ member_id: '__household', display_name: '所有人' }, ...members.filter(m => m.status === 'active')].filter(m => m.display_name.includes(match[1])) : [];
  const selected = Math.min(index, Math.max(0, options.length - 1));
  const choose = (label: string) => {
    if (match) {
      let prefix = text.slice(0, match.index);
      if (label === '所有人') prefix = prefix.replace(/(?:^|\s)@ [^@\s]+/g, '').trimStart();
      else prefix = prefix.replace(/(?:^|\s)@ 所有人\s*/g, '').trimStart();
      onChange(prefix + `@ ${label} `);
    }
    setIndex(0);
  };
  return <div className="board-mention-input">
    {open && <div className="board-mention-menu" role="listbox" aria-label="便笺接收人" id={id}>
      <small>共享便笺给 · 支持选择多位成员</small>
      {options.map((option, i) => <button type="button" id={`${id}-${i}`} role="option" aria-selected={i === selected} key={option.member_id} onClick={() => choose(option.display_name)}>{option.display_name}{option.member_id === '__household' && <small>当前家庭</small>}</button>)}
      {!options.length && <span>没有匹配成员，可在便笺卡片中选择。</span>}
    </div>}
    {children({ menuId: open ? id : undefined, activeOptionId: open && options.length ? `${id}-${selected}` : undefined, handleBoardKey: key => {
      if (!open) return false;
      if (key === 'Escape') { setDismissed(text); return true; }
      if (key === 'ArrowDown' || key === 'ArrowUp') { setIndex((selected + (key === 'ArrowDown' ? 1 : Math.max(options.length - 1, 0))) % Math.max(1, options.length)); return true; }
      if (key === 'Enter') { if (options[selected]) choose(options[selected].display_name); return true; }
      return false;
    } })}
  </div>;
}
