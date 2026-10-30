import { PasskeySettings } from '../auth/PasskeySettings';
import { useEffect, useRef, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  CalendarDays,
  Download,
  LayoutDashboard,
  Users,
  Settings,
  Wrench,
} from 'lucide-react';
import { authApi } from '../../api/auth';
import { homeApi } from '../../api/home';
import { isAdmin, useAppStore } from '../../stores/appStore';
import { formatTime } from '../../utils/format';
import { TaskAdmin } from '../tasks/TaskAdmin';
import { ChatNotificationSettings } from '../pwa/ChatNotificationSettings';
import { validMoreSection } from './moreNavigation';
import { SkillsView } from '../plugins/SkillsView';
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
  if (section && !validMoreSection(section, isAdmin(user))) {
    return <Navigate to="/home/more" replace />;
  }
  return (
    <section className="home-section home-more" aria-label="更多内容">
      {!section && (
        <>
          <p className="home-muted home-more-intro">管理个人偏好，查找便捷工具。</p>
          <section className="home-more-group" aria-labelledby="more-personal">
            <h2 id="more-personal">个人设置</h2>
            <div className="home-more-menu">
              <Link to="/home/more?section=account">
                <Settings size={21} aria-hidden="true" />
                <span>账号与设置<small>外观、通知、通行密钥与登录</small></span>
                <ArrowRight size={18} aria-hidden="true" />
              </Link>
            </div>
          </section>
          <section className="home-more-group" aria-labelledby="more-tools">
            <h2 id="more-tools">便捷使用</h2>
            <div className="home-more-menu">
              <Link to="/home/more?section=skills"><Wrench size={21} aria-hidden="true" />
                <span>技能<small>查看、添加和重载对话技能</small></span>
                <ArrowRight size={18} aria-hidden="true" /></Link>
              <Link to="/install"><Download size={21} aria-hidden="true" />
                <span>添加到主屏幕<small>从手机桌面快速打开</small></span>
                <ArrowRight size={18} aria-hidden="true" /></Link>
              <Link to="/home/more?section=activity"><CalendarDays size={21} aria-hidden="true" />
                <span>物品操作记录<small>查看家庭物品的添加、修改和使用记录</small></span>
                <ArrowRight size={18} aria-hidden="true" /></Link>
            </div>
          </section>
          {isAdmin(user) && (
            <section className="home-more-group" aria-labelledby="more-admin">
              <h2 id="more-admin">管理员工具</h2>
              <div className="home-more-menu">
                <Link to="/home/more?section=admin"><Users size={21} aria-hidden="true" />
                  <span>家庭成员管理<small>账号绑定与历史迁移核对</small></span>
                  <ArrowRight size={18} aria-hidden="true" /></Link>
                <Link to="/dashboard"><LayoutDashboard size={21} aria-hidden="true" />
                  <span>管理看板<small>查看模型用量与运行统计</small></span>
                  <ArrowRight size={18} aria-hidden="true" /></Link>
              </div>
            </section>
          )}
        </>
      )}
      {section === 'skills' && <SkillsView />}
      {section === 'admin' && isAdmin(user) && <TaskAdmin />}
      {section === 'account' && (
        <div className="home-account">
          <h2>{user?.display_name || user?.username}</h2>
          <p className="home-muted">账号：{user?.username}</p>
          <ThemeSelector />
          <ChatNotificationSettings />
          <PasskeySettings />
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
