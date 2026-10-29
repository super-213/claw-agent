import { ArrowDown, ArrowUp, CornerDownLeft, Search, Sparkles } from 'lucide-react';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { skillsApi } from '../../api/skills';
import type { Skill } from '../../api/types';
import { useAppStore } from '../../stores/appStore';
import '../tasks/task-command-input.css';

export function SkillCommandInput({ text, onChange, disabled, onFocusInput, children }: {
  text: string; onChange: (text: string) => void; disabled?: boolean; onFocusInput: () => void;
  children: (bindings: { handleSkillKey: (key: string) => boolean; menuId?: string; activeOptionId?: string }) => ReactNode;
}) {
  const id = useId();
  const userId = useAppStore(s => s.currentUser?.id);
  const shell = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [selection, setSelection] = useState({ text, index: 0 });
  // The space is intentional: a bare "$" or "$name" is ordinary text.
  const match = /^\$ ([^\s]*)$/.exec(text);
  const prefix = !!match;
  useEffect(() => {
    if (!prefix || disabled) return;
    let active = true;
    setLoading(true); setError(''); setSkills([]);
    void skillsApi.list().then(result => { if (active) setSkills(result.skills); })
      .catch(() => { if (active) setError('技能列表加载失败'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [prefix, disabled, userId, retry]);
  useEffect(() => { setDismissed(null); }, [text]);
  useEffect(() => {
    const outside = (event: globalThis.PointerEvent) => {
      if (event.target instanceof Node && !shell.current?.contains(event.target)) setDismissed(text);
    };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [text]);
  const open = prefix && !disabled && dismissed !== text;
  const query = (match?.[1] || '').toLowerCase();
  const choices = skills.filter(skill => `${skill.name} ${skill.summary || ''}`.toLowerCase().includes(query));
  const index = selection.text === text ? selection.index % Math.max(choices.length, 1) : 0;
  const optionId = (i: number) => `${id}-skill-${i}`;
  const select = (skill: Skill) => { onChange(`$ ${skill.name} `); onFocusInput(); };
  const handleSkillKey = (key: string) => {
    if (!open) return false;
    if (key === 'Escape') { setDismissed(text); return true; }
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      const next = (index + (key === 'ArrowDown' ? 1 : Math.max(choices.length, 1) - 1)) % Math.max(choices.length, 1);
      setSelection({ text, index: next });
      list.current?.querySelector<HTMLElement>(`[data-index="${next}"]`)?.scrollIntoView?.({ block: 'nearest' });
      return true;
    }
    if (key === 'Tab' && (loading || !choices.length)) return false;
    if (key === 'Enter' || key === 'Tab') {
      if (!loading && choices[index]) select(choices[index]);
      return true;
    }
    return false;
  };
  return <div ref={shell} style={{ display: 'contents' }}>
    {open && <div className="task-invocation-picker" onMouseDown={event => event.preventDefault()}>
      <div className="task-picker-heading"><Sparkles size={14} /><span>选择技能</span><kbd>$</kbd></div>
      <div ref={list} id={id} role="listbox" aria-label="已注册技能" className="task-picker-list" aria-busy={loading}>
        {!loading && !error && choices.map((skill, i) => <button key={skill.name} id={optionId(i)} data-index={i}
          role="option" aria-selected={index === i} tabIndex={-1} type="button" className="task-picker-option" onClick={() => select(skill)}>
          <span className="task-picker-icon"><Sparkles size={15} /></span>
          <span className="task-picker-copy"><strong>$ {skill.name}</strong><small>{skill.summary || '使用此技能处理任务'}</small></span>
          {index === i && <CornerDownLeft size={13} className="task-picker-return" />}
        </button>)}
        {(loading || error || !choices.length) && <div className="task-picker-empty"><Search size={17} /><span>{loading ? '正在加载技能…' : error || (skills.length ? '没有匹配的技能' : '尚未注册技能')}</span>
          {error && <button type="button" onClick={() => setRetry(value => value + 1)}>重试</button>}</div>}
      </div>
      <div className="task-picker-footer" aria-hidden="true"><span><CornerDownLeft size={11} /> 选择</span><span><ArrowUp size={10} /><ArrowDown size={10} /> 浏览</span><span><kbd>esc</kbd> 关闭</span></div>
    </div>}
    {children({ handleSkillKey, menuId: open ? id : undefined, activeOptionId: open && !loading && choices.length ? optionId(index) : undefined })}
  </div>;
}
