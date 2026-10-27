import { useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  Bot, CalendarDays, ChevronRight, Download, LayoutDashboard,
  MessageCircle, Settings, Users,
} from 'lucide-react';
import { isAdmin, useAppStore } from '../../stores/appStore';

const shortcuts = [
  { path: '/home/more?section=sessions', label: '最近对话', icon: MessageCircle },
  { path: '/home/more?section=activity', label: '家庭动态', icon: CalendarDays },
  { path: '/home/more?section=account', label: '账号与设置', icon: Settings },
  { path: '/install', label: '添加到主屏幕', icon: Download },
];
const adminShortcuts = [
  { path: '/home/more?section=admin', label: '成员与迁移管理', icon: Users },
  { path: '/dashboard', label: '管理看板', icon: LayoutDashboard },
];

export function HomeAgentMenu({ onLeave }: { onLeave?: () => void }) {
  const [open, setOpen] = useState(false);
  const user = useAppStore((state) => state.currentUser);
  const location = useLocation();
  const panelId = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = panel.current;
    if (!open || !element || !('showPopover' in element)) return;
    element.setAttribute('popover', 'auto');
    const rect = trigger.current?.getBoundingClientRect();
    if (rect) { element.style.top = `${rect.bottom + 8}px`; element.style.left = `${Math.min(rect.left, Math.max(8, window.innerWidth - 280))}px`; }
    const toggle = (event: Event) => {
      if ((event as ToggleEvent).newState === 'closed') setOpen(false);
    };
    element.addEventListener('toggle', toggle);
    element.showPopover();
    return () => element.removeEventListener('toggle', toggle);
  }, [open]);

  useEffect(() => setOpen(false), [location.key, user?.id]);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: globalThis.PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, [open]);

  const links = (items: typeof shortcuts) => items.map(({ path, label, icon: Icon }) => (
    <Link key={path} to={path} onClick={() => {
      setOpen(false);
      onLeave?.();
    }}>
      <Icon size={18} aria-hidden="true" />
      <span>{label}</span>
    </Link>
  ));

  return (
    <div className="home-agent-menu" ref={root} onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
    }} onKeyDown={(event) => {
      if (open && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        const links = Array.from(panel.current?.querySelectorAll<HTMLAnchorElement>('a') || []);
        if (links.length) {
          event.preventDefault();
          const index = links.indexOf(document.activeElement as HTMLAnchorElement);
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? links.length - 1 :
            (index + (event.key === 'ArrowUp' ? -1 : 1) + links.length) % links.length;
          links[next].focus();
        }
      }
      if (event.key === 'Escape' && open) {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        trigger.current?.focus();
      }
    }}>
      <button className="home-brand" type="button" ref={trigger}
        aria-label="家庭 Agent 快捷导航" aria-expanded={open} aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}>
        <Bot className="home-brand-icon" size={26} aria-hidden="true" />
        <span>家庭<br />Agent</span>
        <ChevronRight className="home-brand-chevron" size={12} aria-hidden="true" />
      </button>
      {open && (
        <div className="home-agent-popover" id={panelId} ref={panel}>
          <div className="home-agent-menu-heading">家庭 Agent</div>
          <nav className="home-agent-shortcuts" aria-label="家庭 Agent 快捷入口">
            {links(shortcuts)}
            {isAdmin(user) && <div className="home-agent-admin">{links(adminShortcuts)}</div>}
          </nav>
        </div>
      )}
    </div>
  );
}
