import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  CalendarDays,
  MessageCircle,
  Settings,
} from 'lucide-react';
import { authApi } from '../../api/auth';
import { homeApi } from '../../api/home';
import { isAdmin, useAppStore } from '../../stores/appStore';
import { formatTime } from '../../utils/format';
import { TaskAdmin } from '../tasks/TaskAdmin';
import { ChatNotificationSettings } from '../pwa/ChatNotificationSettings';
import { ThemeSelector } from '../../components/ui/ThemeSelector';

export function MoreView({
  section,
  onSettings,
  onOpenChat,
  onNewChat,
  sessions,
  loadSessions,
}: {
  section: string | null;
  onSettings: () => void;
  onOpenChat: (id: string) => void;
  onNewChat: () => Promise<void>;
  sessions: ReturnType<typeof useAppStore.getState>['sessions'];
  loadSessions: () => Promise<void>;
}) {
  const navigate = useNavigate();
  const user = useAppStore((s) => s.currentUser);
  const activity = useQuery({
    queryKey: ['home', user?.id, 'activity'],
    queryFn: homeApi.activity,
    enabled: section === 'activity',
  });
  const [sessionError, setSessionError] = useState('');
  const [sessionLoading, setSessionLoading] = useState(false);
  const loadRef = useRef(loadSessions);
  loadRef.current = loadSessions;
  useEffect(() => {
    if (section !== 'sessions') return;
    let live = true;
    setSessionLoading(true);
    setSessionError('');
    void loadRef
      .current()
      .catch((e) => {
        if (live) setSessionError(e.message);
      })
      .finally(() => {
        if (live) setSessionLoading(false);
      });
    return () => {
      live = false;
    };
  }, [section]);
  const actions: Record<string, string> = {
    'inventory.add': '添加了',
    'inventory.merge': '补充了',
    'inventory.replace': '更新了',
    'inventory.update': '更新了',
    'inventory.delete': '删除了',
    'inventory.consume': '使用了',
  };
  if (section === 'admin' && isAdmin(user)) return <TaskAdmin />;
  return (
    <section className="home-section home-more">
      <h1>
        {section === 'sessions'
          ? '最近对话'
          : section === 'activity'
            ? '家庭动态'
            : section === 'account'
              ? '账号与设置'
              : '更多'}
      </h1>
      {!section && (
        <div className="home-more-menu">
          <Link to="/install">添加到主屏幕 <ArrowRight size={18} /></Link>
          <button onClick={() => navigate('/home/more?section=sessions')}>
            <MessageCircle size={21} />
            最近对话
            <ArrowRight size={18} />
          </button>
          <button onClick={() => navigate('/home/more?section=activity')}>
            <CalendarDays size={21} />
            家庭动态
            <ArrowRight size={18} />
          </button>
          <button onClick={() => navigate('/home/more?section=account')}>
            <Settings size={21} />
            账号与设置
            <ArrowRight size={18} />
          </button>
          {isAdmin(user) && (
            <>
              <button onClick={() => navigate('/home/more?section=admin')}>
                成员与迁移管理
                <ArrowRight size={18} />
              </button>
              <Link to="/dashboard">
                管理看板 <ArrowRight size={18} />
              </Link>
            </>
          )}
        </div>
      )}
      {!section && <ThemeSelector />}
      {section === 'account' && (
        <div className="home-account">
          <h2>{user?.display_name || user?.username}</h2>
          <p className="home-muted">账号：{user?.username}</p>
          <ChatNotificationSettings />
          {isAdmin(user) && (
            <button type="button" onClick={onSettings}>
              模型与设备设置（管理员）
            </button>
          )}
          <button
            type="button"
            onClick={() =>
              void authApi
                .logout()
                .then(() => window.location.assign('/login'))
                .catch((e) => setSessionError(e.message))
            }
          >
            退出登录
          </button>
          {sessionError && <p role="alert">{sessionError}</p>}
        </div>
      )}
      {section === 'sessions' && (
        <>
          <button
            className="home-primary"
            type="button"
            onClick={() =>
              void onNewChat().catch((e) => setSessionError(e.message))
            }
          >
            新建对话
          </button>
          {sessionError && (
            <p role="alert">
              {sessionError}
              <button
                onClick={() =>
                  void loadSessions()
                    .then(() => setSessionError(''))
                    .catch((e) => setSessionError(e.message))
                }
              >
                重试
              </button>
            </p>
          )}
          <div className="home-list">
            {sessions.map((session) => (
              <button
                className="home-session-row"
                type="button"
                key={session.id}
                onClick={() => onOpenChat(session.id)}
              >
                <strong>{session.title || '新对话'}</strong>
                <small>
                  {formatTime(session.updated_at || session.created_at)}
                </small>
                <ArrowRight size={16} />
              </button>
            ))}
          </div>
          {sessionLoading && <p role="status">正在读取对话…</p>}
          {!sessionLoading && !sessions.length && !sessionError && (
            <p className="home-empty">还没有对话，可以新建一段。</p>
          )}
        </>
      )}
      {section === 'activity' && (
        <>
          <p className="home-muted">物品操作记录 · 最近 100 条</p>
          {activity.isPending && <p role="status">正在读取动态…</p>}
          {activity.isError && (
            <p role="alert">
              暂时无法读取动态。
              <button type="button" onClick={() => void activity.refetch()}>
                重试
              </button>
            </p>
          )}
          <div className="home-list">
            {[...(activity.data?.activity || [])]
              .sort((a, b) => b.at.localeCompare(a.at))
              .map((entry) => (
                <article className="home-activity-row" key={entry.id}>
                  <strong>
                    {entry.actor_name || '家庭成员'}
                    {actions[entry.action] || '操作了'}
                    {entry.after?.name || entry.before?.name || '物品'}
                  </strong>
                  <small>{formatTime(entry.at)}</small>
                </article>
              ))}
          </div>
          {activity.data && !activity.data.activity.length && (
            <p className="home-empty">还没有物品操作记录。</p>
          )}
        </>
      )}
    </section>
  );
}
