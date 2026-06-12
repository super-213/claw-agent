import { BarChart3, Bot, Home, LogOut, Menu, MoreHorizontal, Plus, RefreshCcw, Settings, Shield, Wrench, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { SessionSummary, Skill, User } from '../../api/types';
import { formatTime, formatTokens } from '../../utils/format';
import { isAdmin } from '../../stores/appStore';

interface SessionSidebarProps {
  open: boolean;
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
  onOpenConfig: () => void;
  onOpenUsers: () => void;
  onLogout: () => void | Promise<void>;
}

const canManageShare = (session: SessionSummary, user: User | null) =>
  user?.role === 'admin' || session.owner_user_id === user?.id;

const canDelete = (session: SessionSummary, user: User | null) => user?.role === 'admin' || session.owner_user_id === user?.id;

export function SessionSidebar({
  open,
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
  onOpenConfig,
  onOpenUsers,
  onLogout,
}: SessionSidebarProps) {
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const accountMenuRef = useRef<HTMLDivElement | null>(null);
  const orderedSessions = currentSessionId
    ? [
        ...sessions.filter((session) => session.id === currentSessionId),
        ...sessions.filter((session) => session.id !== currentSessionId),
      ]
    : sessions;
  const busyCount = orderedSessions.filter((session) => busySessionIds.has(session.id)).length;
  const currentSession = orderedSessions.find((session) => session.id === currentSessionId) || orderedSessions[0];

  useEffect(() => {
    if (!accountMenuOpen) return;
    const closeOnOutside = (event: MouseEvent) => {
      if (!accountMenuRef.current?.contains(event.target as Node)) {
        setAccountMenuOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAccountMenuOpen(false);
    };
    document.addEventListener('mousedown', closeOnOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('mousedown', closeOnOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [accountMenuOpen]);

  return (
    <>
      <aside className={`sidebar${open ? ' open' : ''}`} aria-label="历史对话">
        <div className="brand-area">
          <button className="sidebar-close" type="button" aria-label="关闭历史对话" onClick={onCloseMobile}>
            <X size={18} />
          </button>
          <div className="brand-head" ref={accountMenuRef}>
            <button
              className="brand-icon brand-menu-trigger"
              type="button"
              aria-label="打开账号与管理菜单"
              aria-expanded={accountMenuOpen}
              aria-haspopup="dialog"
              onClick={() => setAccountMenuOpen((value) => !value)}
            >
              <Bot size={19} />
            </button>
            {accountMenuOpen ? (
              <div className="account-popover" role="dialog" aria-label="账号与管理">
                <div className="account-popover-head">
                  <span>当前用户</span>
                  <strong>{currentUser ? currentUser.display_name || currentUser.username : '未登录'}</strong>
                  <small>{currentUser?.role || 'guest'}</small>
                </div>
                <div className="account-action-grid" aria-label="账号操作">
                  <a className="dashboard-btn" href="/home" title="家庭事务" onClick={() => setAccountMenuOpen(false)}>
                    <Home size={14} />
                    <span>家庭</span>
                  </a>
                  <a className="dashboard-btn" href="/dashboard" title="后台看板" onClick={() => setAccountMenuOpen(false)}>
                    <BarChart3 size={14} />
                    <span>看板</span>
                  </a>
                  {isAdmin(currentUser) ? (
                    <button
                      className="user-admin-btn"
                      type="button"
                      title="用户管理"
                      onClick={() => {
                        setAccountMenuOpen(false);
                        onOpenUsers();
                      }}
                    >
                      <Shield size={14} />
                      <span>用户</span>
                    </button>
                  ) : null}
                  {isAdmin(currentUser) ? (
                    <button
                      className="config-btn"
                      type="button"
                      title="模型设置"
                      onClick={() => {
                        setAccountMenuOpen(false);
                        onOpenConfig();
                      }}
                    >
                      <Settings size={14} />
                      <span>设置</span>
                    </button>
                  ) : null}
                  <button
                    className="logout-btn"
                    type="button"
                    title="退出登录"
                    onClick={() => {
                      setAccountMenuOpen(false);
                      void onLogout();
                    }}
                  >
                    <LogOut size={14} />
                    <span>退出</span>
                  </button>
                </div>
                <div className="sys-status">
                  <div className="dot" />
                  <span>System Online</span>
                </div>
              </div>
            ) : null}
          </div>
          <div className="brand-name">
            <span>Claw</span> Agent
          </div>
          <div className="brand-tag">AI 工作台</div>
          <div className="workspace-summary" aria-label="工作台概览">
            <div>
              <span>会话</span>
              <strong>{sessions.length}</strong>
            </div>
            <div>
              <span>运行</span>
              <strong>{busyCount}</strong>
            </div>
            <div>
              <span>技能</span>
              <strong>{skills.length}</strong>
            </div>
          </div>
        </div>
        <div className="sidebar-actions">
          <button className="new-btn" type="button" onClick={() => void onCreateSession()}>
            <Plus size={16} />
            新建对话
          </button>
        </div>
        <div className="current-context" aria-label="当前上下文">
          <span>当前会话</span>
          <strong>{currentSession?.title || '新对话'}</strong>
          <small>{currentSession ? `${formatTime(currentSession.updated_at || currentSession.created_at)} · ${formatTokens(currentSession.token_usage?.total_tokens)} tok` : '等待创建'}</small>
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
              const scopeLabel = sharing.scope === 'all' ? 'ALL' : sharing.scope === 'selected' ? 'SHARED' : '';
              const menuOpen = menuSessionId === session.id;
              return (
                <div
                  key={session.id}
                  className={`session-item${session.id === currentSessionId ? ' active' : ''}${menuOpen ? ' menu-open' : ''}${busy ? ' busy' : ''}`}
                  onClick={() => void onOpenSession(session.id)}
                >
                  <div className="session-content">
                    <div className="session-title">
                      {session.title || '新对话'}
                      {scopeLabel ? <span className="session-scope">{scopeLabel}</span> : null}
                      {busy ? <span className="session-busy-dot" title="生成中" /> : null}
                    </div>
                    <div className="session-time">
                      {formatTime(session.updated_at || session.created_at)} · {formatTokens(session.token_usage?.total_tokens)} tok
                    </div>
                  </div>
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
          <section className="sidebar-section skill-panel" aria-label="技能">
            <div className="sidebar-section-head">
              <span>技能</span>
              <strong>{skills.length}</strong>
            </div>
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
          </section>
        </div>
      </aside>
      <div className={`sidebar-backdrop${open ? ' open' : ''}`} aria-hidden="true" onClick={onCloseMobile} />
    </>
  );
}

export function MobileMenuButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button className="mobile-menu-btn" type="button" aria-label="打开历史对话" aria-expanded={open} onClick={onClick}>
      <Menu size={20} />
    </button>
  );
}
