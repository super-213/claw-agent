import { useEffect, useRef, useState } from 'react';
import { Wrench } from 'lucide-react';
import type { ActivityKind } from '../../api/familyActivities';
import './activities.css';
export function ActivityToolMenu({ onCreate, disabled }: { onCreate: (kind: ActivityKind) => void; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    const outside = (event: globalThis.PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', outside); return () => document.removeEventListener('pointerdown', outside);
  }, [open]);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  return <div className="board-tools" ref={root} onKeyDown={event => {
    if (event.key === 'Escape') { event.stopPropagation(); close(); }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) && open) {
      event.preventDefault(); const items = Array.from(root.current!.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      items[event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    }
    if (event.key === 'Tab') setOpen(false);
  }}>
    <button type="button" ref={trigger} disabled={disabled} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}><Wrench size={16} />工具</button>
    {open && <div role="menu" aria-label="家庭工具" className="board-tools-menu">
      <button role="menuitem" type="button" onClick={() => { close(); onCreate('relay'); }}>新建家庭接龙</button>
      <button role="menuitem" type="button" onClick={() => { close(); onCreate('poll'); }}>新建家庭投票</button>
    </div>}
  </div>;
}
