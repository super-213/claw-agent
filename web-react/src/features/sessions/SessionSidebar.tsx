import { BarChart3, LogOut, Menu, Plus, RefreshCcw, Settings, Shield, Wrench, X } from 'lucide-react';
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
  return (
    <>
      <aside className={`sidebar${open ? ' open' : ''}`} aria-label="历史对话">
        <div className="brand-area">
          <button className="sidebar-close" type="button" aria-label="关闭历史对话" onClick={onCloseMobile}>
            <X size={18} />
          </button>
          <div className="brand-icon">⚡</div>
          <div className="brand-name">
            <span>Claw</span> Agent
          </div>
          <div className="brand-tag">// React Console</div>
        </div>
        <div className="sidebar-actions">
          <button className="new-btn" type="button" onClick={() => void onCreateSession()}>
            <Plus size={16} />
            新建对话
          </button>
        </div>
        <div className="section-label">// Sessions</div>
        <div className="session-list">
          {sessions.map((session) => {
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
                  ⋯
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
        <div className="skill-panel">
          <div className="section-label">// Skills</div>
          <div className="skill-toolbar">
            <button className="skill-add-btn" type="button" onClick={onOpenSkillModal}>
              <Wrench size={14} />
              添加技能
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
        </div>
        <div className="sidebar-footer">
          <div className="user-summary">
            <span>当前用户</span>
            <strong>
              {currentUser ? `${currentUser.display_name || currentUser.username} · ${currentUser.role}` : '-'}
            </strong>
          </div>
          <div className="sidebar-action-grid" aria-label="账号操作">
            {isAdmin(currentUser) ? (
              <button className="user-admin-btn" type="button" title="用户管理" onClick={onOpenUsers}>
                <Shield size={14} />
              </button>
            ) : null}
            <a className="dashboard-btn" href="/dashboard" title="后台看板">
              <BarChart3 size={14} />
            </a>
            {isAdmin(currentUser) ? (
              <button className="config-btn" type="button" title="模型设置" onClick={onOpenConfig}>
                <Settings size={14} />
              </button>
            ) : null}
            <button className="logout-btn" type="button" title="退出登录" onClick={() => void onLogout()}>
              <LogOut size={14} />
            </button>
          </div>
          <div className="sys-status">
            <div className="dot" />
            <span>System Online</span>
          </div>
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
