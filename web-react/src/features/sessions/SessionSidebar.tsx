import { Menu, MessageCircle, MoreHorizontal, Plus, RefreshCcw, Wrench, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { SessionSummary, Skill, User } from '../../api/types';
import { formatTime } from '../../utils/format';
import { useDialog } from '../../components/ui/useDialog';

interface SessionSidebarProps {
  open: boolean;
  collapsed: boolean;
  sessions: SessionSummary[];
  skills: Skill[];
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
  onInsertSkill: (skill: Skill) => void;
  onOpenSkillModal: () => void;
  onReloadSkills: () => void | Promise<void>;
}

const canManageShare = (session: SessionSummary, user: User | null) =>
  user?.role === 'admin' || session.owner_user_id === user?.id;

const canDelete = (session: SessionSummary, user: User | null) => user?.role === 'admin' || session.owner_user_id === user?.id;

export function SessionSidebar({
  open,
  collapsed,
  sessions,
  skills,
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
  onInsertSkill,
  onOpenSkillModal,
  onReloadSkills,
}: SessionSidebarProps) {
  const orderedSessions = currentSessionId
    ? [
        ...sessions.filter((session) => session.id === currentSessionId),
        ...sessions.filter((session) => session.id !== currentSessionId),
      ]
    : sessions;
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 860px)').matches);
  const { ref: sidebarRef, dismiss } = useDialog(open && isMobile, onCloseMobile);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 860px)');
    const update = () => setIsMobile(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    if (sidebarRef.current) sidebarRef.current.inert = isMobile && !open;
  }, [isMobile, open, sidebarRef]);

  return (
    <div className="sidebar-layer" ref={sidebarRef}>
      <div id="chat-session-sidebar" className={`sidebar${open ? ' open' : ''}`} hidden={collapsed && !isMobile} role={isMobile && open ? "dialog" : "complementary"} aria-modal={isMobile && open ? true : undefined} aria-label="历史对话" tabIndex={-1}>
        <div className="session-sidebar-heading">
          <h2>对话</h2>
          <button className="sidebar-close" type="button" aria-label="关闭历史对话" onClick={dismiss}>
            <X size={18} />
          </button>
        </div>
        <div className="sidebar-actions">
          <button className="new-btn" type="button" onClick={() => void onCreateSession()}>
            <Plus size={16} />
            新建对话
          </button>
        </div>
        <div className="history-panel">
          <div className="history-toggle" id="session-history-heading">
            <span>会话历史</span>
            <strong>{sessions.length}</strong>
          </div>
          <div className="session-list" id="session-history-list">
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
                  <button type="button" className="session-open" aria-current={session.id === currentSessionId ? "page" : undefined} onClick={() => void onOpenSession(session.id)}>
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

        <div className="sidebar-utilities">
          <details className="sidebar-section skill-panel">
            <summary className="sidebar-section-head">
              <span><Wrench size={15} /> 技能</span>
              <strong>{skills.length}</strong>
            </summary>
            <div className="skill-toolbar">
              <button className="skill-add-btn" type="button" onClick={onOpenSkillModal}>
                <Wrench size={14} />
                添加
              </button>
              <button className="skill-reload-btn" type="button" title="重载技能" aria-label="重载技能" onClick={() => void onReloadSkills()}>
                <RefreshCcw size={14} />
              </button>
            </div>
            <div className="skill-list">
              {skills.length ? (
                skills.map((skill) => (
                  <button key={skill.name} className="skill-item" type="button" title={`插入调用 ${skill.name} skill`} onClick={() => onInsertSkill(skill)}>
                    {skill.name}
                  </button>
                ))
              ) : (
                <div className="skill-empty">暂无技能</div>
              )}
            </div>
          </details>
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
