import { Menu, MessageCircle, MoreHorizontal, SquarePen, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import type { SessionSummary, User } from '../../api/types';
import { formatTime } from '../../utils/format';
import { useDialog } from '../../components/ui/useDialog';

interface SessionSidebarProps {
  open: boolean;
  collapsed: boolean;
  sessions: SessionSummary[];
  currentSessionId: string | null;
  currentUser: User | null;
  busySessionIds: Set<string>;
  menuSessionId: string | null;
  onCloseMobile: () => void;
  onCreateSession: () => void | Promise<void>;
  onOpenSession: (sessionId: string) => void | Promise<void>;
  onToggleSessionMenu: (sessionId: string | null) => void;
  onCopySession: (sessionId: string) => void | Promise<void>;
  onDeleteSession: (sessionId: string) => void | Promise<void>;
  onShareSession: (sessionId: string) => void | Promise<void>;
}

const canManageShare = (session: SessionSummary, user: User | null) =>
  user?.role === 'admin' || session.owner_user_id === user?.id;

const canDelete = (session: SessionSummary, user: User | null) => user?.role === 'admin' || session.owner_user_id === user?.id;

export function SessionSidebar({
  open,
  collapsed,
  sessions,
  currentSessionId,
  currentUser,
  busySessionIds,
  menuSessionId,
  onCloseMobile,
  onCreateSession,
  onOpenSession,
  onToggleSessionMenu,
  onCopySession,
  onDeleteSession,
  onShareSession,
}: SessionSidebarProps) {
  const orderedSessions = currentSessionId
    ? [
        ...sessions.filter((session) => session.id === currentSessionId),
        ...sessions.filter((session) => session.id !== currentSessionId),
      ]
    : sessions;
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 860px)').matches);
  const press = useRef<{ pointerId: number; x: number; y: number; timer: number } | null>(null);
  const suppressClick = useRef<string | null>(null);
  const cancelPress = () => {
    if (press.current) window.clearTimeout(press.current.timer);
    press.current = null;
  };
  const startPress = (event: ReactPointerEvent<HTMLButtonElement>, sessionId: string) => {
    cancelPress();
    suppressClick.current = null;
    if (!isMobile || !open || event.pointerType !== 'touch' || !event.isPrimary) return;
    press.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      timer: window.setTimeout(() => {
        suppressClick.current = sessionId;
        onToggleSessionMenu(sessionId);
      }, 500),
    };
  };
  const { ref: sidebarRef, dismiss } = useDialog(open && isMobile, onCloseMobile);
  useEffect(() => {
    // A closed drawer, changed viewport or unmounted list cannot finish a press.
    return cancelPress;
  }, [open, isMobile, sessions]);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 860px)');
    const update = () => setIsMobile(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    if (sidebarRef.current) sidebarRef.current.inert = isMobile && !open;
  }, [isMobile, open, sidebarRef]);
  useEffect(() => {
    if (isMobile && open && menuSessionId) {
      sidebarRef.current?.querySelector('.session-menu')?.scrollIntoView?.({ block: 'nearest' });
    }
  }, [isMobile, open, menuSessionId, sidebarRef]);

  return (
    <div className="sidebar-layer" ref={sidebarRef}>
      <div id="chat-session-sidebar" className={`sidebar${open ? ' open' : ''}`} hidden={collapsed && !isMobile} role={isMobile && open ? "dialog" : "complementary"} aria-modal={isMobile && open ? true : undefined} aria-label="历史对话" tabIndex={-1}>
        <div className="session-history-header">
          <div className="history-toggle" id="session-history-heading">
            <span>会话历史</span>
            <strong>{sessions.length}</strong>
          </div>
          <button className="sidebar-close" type="button" aria-label="关闭历史对话" onClick={dismiss}>
            <X size={18} />
          </button>
        </div>
        <div className="history-panel">
          <div className="session-list" id="session-history-list" onScroll={cancelPress}>
            {orderedSessions.map((session) => {
              const busy = busySessionIds.has(session.id);
              const sharing = session.sharing || { scope: 'private' };
              const scopeLabel = sharing.scope === 'all' ? '全员共享' : sharing.scope === 'selected' ? '共享' : '';
              const menuOpen = menuSessionId === session.id;
              return (
                <div
                  key={session.id}
                  className={`session-item${session.id === currentSessionId ? ' active' : ''}${menuOpen ? ' menu-open' : ''}${busy ? ' busy' : ''}`}
                >
                  <button
                    type="button"
                    className="session-open"
                    aria-current={session.id === currentSessionId ? 'page' : undefined}
                    onPointerDown={(event) => startPress(event, session.id)}
                    onPointerMove={(event) => {
                      const current = press.current;
                      if (current && current.pointerId === event.pointerId &&
                        Math.hypot(event.clientX - current.x, event.clientY - current.y) > 10) cancelPress();
                    }}
                    onPointerUp={cancelPress}
                    onPointerCancel={cancelPress}
                    onPointerLeave={cancelPress}
                    onContextMenu={(event) => {
                      if (isMobile) event.preventDefault();
                    }}
                    onClick={(event) => {
                      if (suppressClick.current === session.id && event.detail !== 0) {
                        suppressClick.current = null;
                        event.preventDefault();
                        return;
                      }
                      void onOpenSession(session.id);
                    }}
                  >
                    <MessageCircle size={16} aria-hidden="true" />
                    <span className="session-content">
                      <span className="session-title">
                        <span className="session-title-text">{session.title || '新对话'}</span>
                        {scopeLabel ? <span className="session-scope">{scopeLabel}</span> : null}
                        {busy ? <span className="session-busy-dot" title="生成中" /> : null}
                      </span>
                      <span className="session-time">
                        {formatTime(session.updated_at || session.created_at)}
                      </span>
                    </span>
                  </button>
                  <button
                    className="session-more"
                    type="button"
                    title="更多操作"
                    aria-label="更多操作"
                    aria-expanded={menuOpen}
                    onClick={(event) => {
                      event.stopPropagation();
                      onToggleSessionMenu(menuOpen ? null : session.id);
                    }}
                  >
                    <MoreHorizontal size={17} />
                  </button>
                  {menuOpen ? (
                    <div className="session-menu" onClick={(event) => event.stopPropagation()}>
                      <button type="button" onClick={() => void onCopySession(session.id)}>
                        复制会话
                      </button>
                      {canManageShare(session, currentUser) ? (
                        <button type="button" onClick={() => void onShareSession(session.id)}>
                          共享设置
                        </button>
                      ) : null}
                      {canDelete(session, currentUser) ? (
                        <button type="button" className="danger" onClick={() => void onDeleteSession(session.id)}>
                          删除
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        <div className="sidebar-actions">
          <button className="new-btn" type="button" onClick={() => void onCreateSession()}>
            <SquarePen size={18} aria-hidden="true" />
            新建对话
          </button>
        </div>
      </div>
      <div className={`sidebar-backdrop${open ? ' open' : ''}`} aria-hidden="true" onClick={dismiss} />
    </div>
  );
}

export function MobileMenuButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button className="mobile-menu-btn" type="button" aria-label="打开历史对话" aria-expanded={open} aria-controls="chat-session-sidebar" onClick={onClick}>
      <Menu size={20} />
    </button>
  );
}
