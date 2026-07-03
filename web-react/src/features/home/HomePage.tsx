import {
  ArrowRight,
  Bell,
  CalendarDays,
  Camera,
  Check,
  Clock3,
  FileText,
  Home,
  Inbox,
  ListTodo,
  MapPin,
  MessageCircle,
  Mic,
  PackagePlus,
  Pill,
  RefreshCw,
  Search,
  Settings,
  ShoppingBasket,
  Trash2,
  Users,
  Utensils,
  X,
  type LucideIcon,
} from 'lucide-react';
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { configApi } from '../../api/config';
import { homeApi } from '../../api/home';
import { sessionsApi } from '../../api/sessions';
import type { HomeInventoryItem, HomeNotification, HomeReminder, HomeTaskSummary } from '../../api/types';
import { isAdmin, useAppStore } from '../../stores/appStore';
import { formatTime, formatTokens } from '../../utils/format';
import { ChatWorkspace } from '../chat/ChatWorkspace';
import { ConfigModal } from '../settings/ConfigModal';

const statusLabel: Record<string, string> = {
  scheduled: '已排程',
  snoozed: '已延后',
  completed: '已完成',
  cancelled: '已取消',
  sent: '已发送',
  failed: '失败',
};

const channelLabel: Record<string, string> = {
  in_app: '站内',
  web_push: '推送',
  email: '邮件',
  webhook: 'Webhook',
};

const familyNavItems: Array<{ label: string; href: string; icon: LucideIcon }> = [
  { label: '今日概览', href: '#today', icon: Home },
  { label: '空间与物品', href: '#inventory', icon: MapPin },
  { label: '任务提醒', href: '#reminders', icon: ListTodo },
  { label: '家庭时间线', href: '#timeline', icon: CalendarDays },
  { label: '文件', href: '#files', icon: FileText },
];

const objectShortcuts: Array<{ label: string; meta: string; icon: LucideIcon; draft: string }> = [
  { label: '冰箱', meta: '食品、保质期、补货', icon: Utensils, draft: '查看冰箱里需要关注的物品。' },
  { label: '药箱', meta: '药品、用量、提醒', icon: Pill, draft: '帮我检查药箱和用药提醒。' },
  { label: '购物清单', meta: '低库存、采购计划', icon: ShoppingBasket, draft: '根据低库存生成一份购物清单。' },
  { label: '账单文件', meta: '缴费、票据、归档', icon: FileText, draft: '整理最近需要处理的家庭账单。' },
  { label: '家庭成员', meta: '任务归属、通知', icon: Users, draft: '查看每个家庭成员待处理的事项。' },
];

const quickActions: Array<{ label: string; icon: LucideIcon; draft: string }> = [
  { label: '记录冰箱物品', icon: PackagePlus, draft: '我要记录一件冰箱物品：' },
  { label: '创建提醒', icon: Bell, draft: '提醒我：' },
  { label: '拍照识别', icon: Camera, draft: '我想上传图片，让你识别并记录家庭物品。' },
  { label: '处理未读通知', icon: Inbox, draft: '帮我处理家庭通知收件箱里的待确认事项。' },
];

const urlBase64ToUint8Array = (base64String: string) => {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
};

function Kpi({ label, value, icon: Icon }: { label: string; value: number | string; icon: LucideIcon }) {
  return (
    <div className="home-kpi">
      <Icon size={18} />
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function relativeRunTime(value?: string | null) {
  if (!value) return '未设置';
  return formatTime(value);
}

export function HomePage() {
  const sessions = useAppStore((state) => state.sessions);
  const currentSessionId = useAppStore((state) => state.currentSessionId);
  const currentUser = useAppStore((state) => state.currentUser);
  const config = useAppStore((state) => state.config);
  const setSessions = useAppStore((state) => state.setSessions);
  const setConfig = useAppStore((state) => state.setConfig);

  const [items, setItems] = useState<HomeInventoryItem[]>([]);
  const [expiring, setExpiring] = useState<HomeInventoryItem[]>([]);
  const [reminders, setReminders] = useState<HomeReminder[]>([]);
  const [notifications, setNotifications] = useState<HomeNotification[]>([]);
  const [summary, setSummary] = useState<HomeTaskSummary | null>(null);
  const [pushConfigured, setPushConfigured] = useState(false);
  const [pushPermission, setPushPermission] = useState(
    typeof window !== 'undefined' && 'Notification' in window ? window.Notification.permission : 'unsupported',
  );
  const [deviceCount, setDeviceCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [now, setNow] = useState(() => new Date());
  const [commandDraft, setCommandDraft] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [chatOpen, setChatOpen] = useState(false);
  const [chatMounted, setChatMounted] = useState(false);
  const [overlaySessionId, setOverlaySessionId] = useState<string | null>(null);
  const [draftSeed, setDraftSeed] = useState<{ id: number; text: string } | null>(null);
  const draftSeedId = useRef(0);
  const overlayHistoryPushed = useRef(false);

  const [itemDraft, setItemDraft] = useState({ name: '', quantity: '', unit: '个', expires_at: '', zone: '冷藏层' });
  const [reminderDraft, setReminderDraft] = useState({ title: '', raw_text: '' });

  useEffect(() => {
    document.body.classList.add('home-route');
    return () => {
      document.body.classList.remove('home-route');
      document.body.classList.remove('home-chat-open');
    };
  }, []);

  useEffect(() => {
    document.body.classList.toggle('home-chat-open', chatOpen);
    return () => {
      document.body.classList.remove('home-chat-open');
    };
  }, [chatOpen]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const loadRecentSessions = useCallback(async () => {
    const data = await sessionsApi.list();
    setSessions(data);
    return data;
  }, [setSessions]);

  const loadConfig = useCallback(async () => {
    if (!isAdmin(currentUser)) return;
    const data = await configApi.get().catch(() => null);
    if (data) setConfig(data);
  }, [currentUser, setConfig]);

  const load = useCallback(async () => {
    const [inventoryData, expiringData, reminderData, notificationData, summaryData, vapidData, subscriptionData] = await Promise.all([
      homeApi.inventory(),
      homeApi.expiring(3),
      homeApi.reminders(),
      homeApi.notifications(),
      homeApi.taskSummary(),
      homeApi.vapidKey().catch(() => ({ public_key: '', configured: false })),
      homeApi.subscriptions().catch(() => ({ subscriptions: [] })),
    ]);
    setItems(inventoryData.items || []);
    setExpiring(expiringData.items || []);
    setReminders(reminderData.reminders || []);
    setNotifications(notificationData.notifications || []);
    setSummary(summaryData);
    setPushConfigured(Boolean(vapidData.configured));
    setDeviceCount(subscriptionData.subscriptions?.length || 0);
    setPushPermission(typeof window !== 'undefined' && 'Notification' in window ? window.Notification.permission : 'unsupported');
  }, []);

  useEffect(() => {
    void load().catch((error) => setMessage(error.message || '读取家庭数据失败'));
    void loadRecentSessions().catch(() => undefined);
  }, [load, loadRecentSessions]);

  const openConversation = useCallback(
    ({ sessionId, draft }: { sessionId?: string; draft?: string } = {}) => {
      setChatMounted(true);
      if (sessionId) setOverlaySessionId(sessionId);
      if (typeof draft === 'string') {
        draftSeedId.current += 1;
        setDraftSeed({ id: draftSeedId.current, text: draft });
      }
      if (!chatOpen && typeof window !== 'undefined' && !overlayHistoryPushed.current) {
        window.history.pushState({ homeChatOverlay: true }, '', window.location.href);
        overlayHistoryPushed.current = true;
      }
      setChatOpen(true);
    },
    [chatOpen],
  );

  const closeConversation = useCallback(() => {
    if (typeof window !== 'undefined' && overlayHistoryPushed.current) {
      window.history.back();
      return;
    }
    setChatOpen(false);
  }, []);

  useEffect(() => {
    if (!chatOpen) return;
    const onPopState = () => {
      overlayHistoryPushed.current = false;
      setChatOpen(false);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [chatOpen]);

  useEffect(() => {
    if (!chatOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeConversation();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [chatOpen, closeConversation]);

  const todayReminders = useMemo(() => {
    const today = new Date().toDateString();
    return reminders.filter((item) => item.next_run_at && new Date(item.next_run_at).toDateString() === today && item.status !== 'cancelled');
  }, [reminders]);

  const pendingReminders = useMemo(() => reminders.filter((item) => item.status !== 'cancelled' && item.status !== 'completed'), [reminders]);

  const lowStock = useMemo(
    () => items.filter((item) => item.status === 'low' || (typeof item.quantity === 'number' && item.quantity <= 1)),
    [items],
  );

  const unreadNotifications = useMemo(() => notifications.filter((item) => !item.read_at).length, [notifications]);
  const recentSessions = useMemo(() => sessions.slice(0, 6), [sessions]);
  const recentActivities = useMemo(() => {
    const notificationActivities = notifications.slice(0, 4).map((item) => ({
      id: `notification-${item.id}`,
      title: item.title,
      meta: `${item.status || '通知'} · ${item.created_at ? formatTime(item.created_at) : '刚刚'}`,
    }));
    const inventoryActivities = items
      .filter((item) => item.updated_at)
      .slice(0, 3)
      .map((item) => ({
        id: `item-${item.id}`,
        title: `${item.name} 已更新`,
        meta: `${item.zone || '未分区'} · ${formatTime(item.updated_at)}`,
      }));
    return [...notificationActivities, ...inventoryActivities].slice(0, 6);
  }, [items, notifications]);

  const todayLabel = useMemo(
    () =>
      new Intl.DateTimeFormat('zh-CN', {
        month: 'long',
        day: 'numeric',
        weekday: 'long',
        hour: '2-digit',
        minute: '2-digit',
      }).format(now),
    [now],
  );

  const addItem = async (event: FormEvent) => {
    event.preventDefault();
    if (!itemDraft.name.trim()) return;
    setBusy(true);
    try {
      await homeApi.addInventoryItem({
        name: itemDraft.name.trim(),
        quantity: itemDraft.quantity ? Number(itemDraft.quantity) : null,
        unit: itemDraft.unit,
        zone: itemDraft.zone,
        expires_at: itemDraft.expires_at || null,
      });
      setItemDraft({ name: '', quantity: '', unit: '个', expires_at: '', zone: '冷藏层' });
      setMessage('冰箱清单已更新');
      await load();
    } finally {
      setBusy(false);
    }
  };

  const addReminder = async (event: FormEvent) => {
    event.preventDefault();
    if (!reminderDraft.title.trim() && !reminderDraft.raw_text.trim()) return;
    setBusy(true);
    try {
      const rawText = reminderDraft.raw_text.trim() || `${reminderDraft.title.trim()} 提醒我`;
      const result = await homeApi.createReminder({
        title: reminderDraft.title.trim() || '家庭提醒',
        description: reminderDraft.title.trim(),
        raw_text: rawText,
        channels: ['in_app', 'web_push'],
      });
      setReminderDraft({ title: '', raw_text: '' });
      setMessage(result.receipt || '提醒已添加');
      await load();
    } finally {
      setBusy(false);
    }
  };

  const enablePush = async () => {
    setBusy(true);
    try {
      if (!('Notification' in window) || !('serviceWorker' in window.navigator)) {
        setMessage('当前浏览器不支持通知或 Service Worker');
        return;
      }
      const permission = await window.Notification.requestPermission();
      setPushPermission(permission);
      if (permission !== 'granted') {
        setMessage('通知权限未授权');
        return;
      }
      const vapid = await homeApi.vapidKey();
      if (!vapid.configured || !vapid.public_key) {
        setMessage('浏览器通知权限已开启；服务端未配置 VAPID，系统会使用站内通知记录。');
        return;
      }
      const registration = await window.navigator.serviceWorker.register('/sw.js');
      const existing = await registration.pushManager.getSubscription();
      const subscription =
        existing ||
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapid.public_key),
        }));
      await homeApi.saveSubscription({
        subscription: subscription.toJSON(),
        device_name: window.navigator.platform || '当前浏览器',
        user_agent: window.navigator.userAgent,
      });
      setMessage('当前设备通知已启用');
      await load();
    } finally {
      setBusy(false);
    }
  };

  const sendTestPush = async () => {
    setBusy(true);
    try {
      const result = await homeApi.sendTestPush();
      if ('Notification' in window && window.Notification.permission === 'granted') {
        new window.Notification('测试通知', { body: '家庭 Agent 推送已启用' });
      }
      setMessage(result.web_push_configured ? '测试推送已发送' : '测试通知已写入站内通知；Web Push 尚未配置 VAPID');
      await load();
    } finally {
      setBusy(false);
    }
  };

  const startNewConversation = async (draft = '') => {
    setBusy(true);
    try {
      const session = await sessionsApi.create();
      await loadRecentSessions();
      openConversation({ sessionId: session.id, draft });
    } finally {
      setBusy(false);
    }
  };

  const submitCommand = (event: FormEvent) => {
    event.preventDefault();
    const draft = commandDraft.trim();
    openConversation({ draft });
    if (draft) setCommandDraft('');
  };

  const openSettings = () => {
    setSettingsOpen(true);
    void loadConfig();
  };

  return (
    <main className="home-shell" aria-label="家庭 Agent 主工作台">
      <aside className="home-family-nav" aria-label="家庭导航">
        <div className="home-family-brand">
          <div className="home-family-mark">
            <Home size={19} />
          </div>
          <div>
            <strong>家庭 Agent</strong>
            <span>{todayLabel}</span>
          </div>
        </div>

        <nav className="home-family-menu" aria-label="家庭功能">
          {familyNavItems.map((item) => (
            <a href={item.href} key={item.label}>
              <item.icon size={16} />
              <span>{item.label}</span>
            </a>
          ))}
        </nav>

        <section className="home-recent-sessions" aria-label="最近对话">
          <div className="home-sidebar-head">
            <span>最近对话</span>
            <strong>{sessions.length}</strong>
          </div>
          <button className="home-new-chat" type="button" disabled={busy} onClick={() => void startNewConversation()}>
            <MessageCircle size={15} />
            新建对话
          </button>
          <div className="home-session-list">
            {recentSessions.length ? (
              recentSessions.map((session) => (
                <button
                  className={`home-session-item${session.id === currentSessionId ? ' active' : ''}`}
                  type="button"
                  key={session.id}
                  onClick={() => openConversation({ sessionId: session.id })}
                >
                  <span>{session.title || '新对话'}</span>
                  <small>
                    {formatTime(session.updated_at || session.created_at)} · {formatTokens(session.token_usage?.total_tokens)} tok
                  </small>
                </button>
              ))
            ) : (
              <div className="home-sidebar-empty">暂无会话</div>
            )}
          </div>
        </section>
      </aside>

      <section className="home-dashboard-main">
        <header className="home-topbar" id="today">
          <div className="home-title-block">
            <span className="home-kicker">主工作台</span>
            <h1>家庭工作台</h1>
            <p>今日提醒、物品状态、通知和最近协作集中在这里。</p>
          </div>
          <form className="home-global-command" onSubmit={submitCommand}>
            <Search size={17} />
            <input
              aria-label="搜索或输入家庭需求"
              value={commandDraft}
              placeholder="搜索家庭事务，或直接说需求..."
              onChange={(event) => setCommandDraft(event.target.value)}
            />
            <button type="button" title="语音输入" onClick={() => openConversation({ draft: '语音记录：' })}>
              <Mic size={17} />
            </button>
            <button type="submit" title="打开对话覆盖层">
              <ArrowRight size={17} />
            </button>
          </form>
          <nav className="home-nav" aria-label="家庭页面操作">
            <button className="icon-button" type="button" title="刷新" disabled={busy} onClick={() => void load()}>
              <RefreshCw size={18} />
            </button>
            <Link to="/chat" className="home-nav-link">
              <MessageCircle size={15} />
              对话
            </Link>
            <Link to="/dashboard" className="home-nav-link">
              看板
            </Link>
            <button type="button" className="home-nav-link" onClick={openSettings}>
              <Settings size={15} />
              设置
            </button>
          </nav>
        </header>

        {message ? <pre className="home-message">{message}</pre> : null}

        <section className="home-command-board" aria-label="家庭事务概览">
          <article className="home-focus-card">
            <div>
              <span className="home-kicker">Today</span>
              <h2>{pendingReminders.length} 个事项待处理</h2>
              <p>
                {todayReminders.length} 个今日提醒，{expiring.length} 项 3 天内到期，{unreadNotifications} 条未读通知。
              </p>
            </div>
            <div className="home-ops">
              <Kpi icon={Clock3} label="今日提醒" value={todayReminders.length} />
              <Kpi icon={Utensils} label="快过期" value={expiring.length} />
              <Kpi icon={ShoppingBasket} label="低库存" value={lowStock.length} />
              <Kpi icon={Inbox} label="未读通知" value={unreadNotifications} />
            </div>
          </article>

          <section className="home-chat-entry" aria-label="情境化对话入口">
            <form onSubmit={submitCommand}>
              <MessageCircle size={18} />
              <input
                aria-label="对话入口"
                value={commandDraft}
                placeholder="说点什么，或输入 / 创建提醒..."
                onChange={(event) => setCommandDraft(event.target.value)}
              />
              <button type="submit" title="进入对话">
                <ArrowRight size={17} />
              </button>
            </form>
            <div className="home-quick-actions">
              {quickActions.map((action) => (
                <button type="button" key={action.label} onClick={() => openConversation({ draft: action.draft })}>
                  <action.icon size={15} />
                  <span>{action.label}</span>
                </button>
              ))}
            </div>
          </section>
        </section>

        <section className="home-object-strip" aria-label="常用对象">
          {objectShortcuts.map((item) => (
            <button type="button" key={item.label} onClick={() => openConversation({ draft: item.draft })}>
              <item.icon size={17} />
              <span>
                <strong>{item.label}</strong>
                <small>{item.meta}</small>
              </span>
            </button>
          ))}
        </section>

        <div className="home-workbench">
          <section className="home-section home-primary-pane" id="inventory">
            <div className="home-section-head">
              <div>
                <h2>冰箱清单</h2>
                <p>{items.length ? `共 ${items.length} 项，按到期和状态维护。` : '当前冰箱清单为空。'}</p>
              </div>
              <span>{expiring.length} 项 3 天内到期</span>
            </div>
            <form className="home-inline-form" onSubmit={(event) => void addItem(event)}>
              <input aria-label="物品" value={itemDraft.name} placeholder="物品" onChange={(event) => setItemDraft({ ...itemDraft, name: event.target.value })} />
              <input
                aria-label="数量"
                value={itemDraft.quantity}
                placeholder="数量"
                inputMode="decimal"
                onChange={(event) => setItemDraft({ ...itemDraft, quantity: event.target.value })}
              />
              <select aria-label="单位" value={itemDraft.unit} onChange={(event) => setItemDraft({ ...itemDraft, unit: event.target.value })}>
                <option value="个">个</option>
                <option value="盒">盒</option>
                <option value="瓶">瓶</option>
                <option value="斤">斤</option>
                <option value="kg">kg</option>
                <option value="片">片</option>
              </select>
              <input aria-label="到期日期" type="date" value={itemDraft.expires_at} onChange={(event) => setItemDraft({ ...itemDraft, expires_at: event.target.value })} />
              <button type="submit" disabled={busy} title="添加物品">
                <PackagePlus size={16} />
                添加
              </button>
            </form>
            <div className="home-table" role="table" aria-label="冰箱清单">
              <div className="home-row head" role="row">
                <span>物品</span>
                <span>数量</span>
                <span>到期</span>
                <span>状态</span>
                <span>操作</span>
              </div>
              {items.map((item) => (
                <div className={`home-row${expiring.some((entry) => entry.id === item.id) ? ' urgent' : ''}`} role="row" key={item.id}>
                  <span>
                    <strong>{item.name}</strong>
                    <small>
                      {item.category || '其他'} · {item.zone || '未分区'}
                    </small>
                  </span>
                  <span>
                    {item.quantity ?? '未知'}
                    {item.unit}
                  </span>
                  <span>{item.expires_at || '未记录'}</span>
                  <span>{item.status || 'available'}</span>
                  <span className="row-actions">
                    <button type="button" title="标记用完" onClick={() => void homeApi.consumeInventoryItem(item.id).then(load)}>
                      <Check size={15} />
                    </button>
                    <button type="button" title="删除" onClick={() => void homeApi.deleteInventoryItem(item.id).then(load)}>
                      <Trash2 size={15} />
                    </button>
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section className="home-section" id="reminders">
            <div className="home-section-head">
              <div>
                <h2>任务与提醒</h2>
                <p>今日、未来和周期任务统一管理。</p>
              </div>
            </div>
            <form className="home-stack-form" onSubmit={(event) => void addReminder(event)}>
              <input
                aria-label="事件标题"
                value={reminderDraft.title}
                placeholder="事件标题"
                onChange={(event) => setReminderDraft({ ...reminderDraft, title: event.target.value })}
              />
              <input
                aria-label="提醒内容"
                value={reminderDraft.raw_text}
                placeholder="例如：明天早上 8 点提醒我倒垃圾"
                onChange={(event) => setReminderDraft({ ...reminderDraft, raw_text: event.target.value })}
              />
              <button type="submit" disabled={busy}>
                <Bell size={16} />
                添加提醒
              </button>
            </form>
            <div className="home-list">
              {reminders.slice(0, 8).map((reminder) => (
                <article
                  className="home-list-item home-task-card"
                  key={reminder.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => openConversation({ draft: `继续处理提醒：${reminder.title}` })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') openConversation({ draft: `继续处理提醒：${reminder.title}` });
                  }}
                >
                  <div>
                    <strong>{reminder.title}</strong>
                    <small>
                      {relativeRunTime(reminder.next_run_at)} · {statusLabel[reminder.status || ''] || reminder.status}
                    </small>
                  </div>
                  <div className="row-actions">
                    <button
                      type="button"
                      title="完成"
                      onClick={(event) => {
                        event.stopPropagation();
                        void homeApi.completeReminder(reminder.id).then(load);
                      }}
                    >
                      <Check size={15} />
                    </button>
                    <button
                      type="button"
                      title="延后 10 分钟"
                      onClick={(event) => {
                        event.stopPropagation();
                        void homeApi.snoozeReminder(reminder.id, 10).then(load);
                      }}
                    >
                      <Clock3 size={15} />
                    </button>
                    <button
                      type="button"
                      title="取消"
                      onClick={(event) => {
                        event.stopPropagation();
                        void homeApi.cancelReminder(reminder.id).then(load);
                      }}
                    >
                      <X size={15} />
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="home-section home-insights-pane" id="files">
            <div className="home-section-head">
              <div>
                <h2>任务统计</h2>
                <p>后台看板同口径任务汇总。</p>
              </div>
            </div>
            <div className="home-stat-line">
              {(summary?.status_distribution || []).map((item) => (
                <div key={String(item.label)}>
                  <span>{statusLabel[String(item.label)] || String(item.label)}</span>
                  <strong>{Number(item.value || 0)}</strong>
                </div>
              ))}
            </div>
            <div className="home-stat-line">
              {(summary?.channel_distribution || []).map((item) => (
                <div key={String(item.label)}>
                  <span>{channelLabel[String(item.label)] || String(item.label)}</span>
                  <strong>{Number(item.value || 0)}</strong>
                </div>
              ))}
            </div>
            <div className="home-alerts">
              {(summary?.alerts || []).map((alert) => (
                <div key={String(alert.id || alert.title)}>
                  <strong>{String(alert.title || '提示')}</strong>
                  <span>{String(alert.message || '')}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </section>

      <aside className="home-detail-panel" aria-label="详情与通知">
        <section className="home-section">
          <div className="home-section-head">
            <div>
              <h2>详情面板</h2>
              <p>通知权限、来源和状态摘要。</p>
            </div>
          </div>
          <div className="push-state">
            <span>浏览器权限</span>
            <strong>{pushPermission}</strong>
            <span>VAPID</span>
            <strong>{pushConfigured ? '已配置' : '未配置'}</strong>
            <span>绑定设备</span>
            <strong>{deviceCount}</strong>
          </div>
          <div className="home-button-row">
            <button type="button" disabled={busy} onClick={() => void enablePush()}>
              <Bell size={16} />
              启用通知
            </button>
            <button type="button" disabled={busy} onClick={() => void sendTestPush()}>
              <RefreshCw size={16} />
              测试通知
            </button>
          </div>
        </section>

        <section className="home-section">
          <div className="home-section-head">
            <div>
              <h2>通知收件箱</h2>
              <p>{unreadNotifications} 条未读，按状态和来源汇总。</p>
            </div>
          </div>
          <div className="home-list compact">
            {notifications.slice(0, 8).map((notification) => (
              <button className="home-notification" type="button" key={notification.id} onClick={() => void homeApi.readNotification(notification.id).then(load)}>
                <span>{notification.title}</span>
                <small>
                  {notification.status}
                  {notification.reason ? ` · ${notification.reason}` : ''} · {formatTime(notification.created_at)}
                </small>
              </button>
            ))}
          </div>
        </section>

        <section className="home-section" id="timeline">
          <div className="home-section-head">
            <div>
              <h2>最近活动</h2>
              <p>家庭时间线摘要。</p>
            </div>
          </div>
          <div className="home-timeline">
            {recentActivities.length ? (
              recentActivities.map((activity) => (
                <div key={activity.id}>
                  <span />
                  <strong>{activity.title}</strong>
                  <small>{activity.meta}</small>
                </div>
              ))
            ) : (
              <p className="home-sidebar-empty">暂无活动</p>
            )}
          </div>
        </section>
      </aside>

      {chatMounted ? (
        <div className={`home-chat-overlay${chatOpen ? ' open' : ''}`} aria-hidden={!chatOpen}>
          <div className="home-chat-scrim" onClick={closeConversation} />
          <section className="home-chat-layer" role="dialog" aria-modal={chatOpen} aria-label="对话覆盖层">
            <ChatWorkspace
              mode="overlay"
              active={chatOpen}
              requestedSessionId={overlaySessionId}
              draftSeed={draftSeed}
              onClose={closeConversation}
              onSessionChange={setOverlaySessionId}
            />
          </section>
        </div>
      ) : null}

      <ConfigModal
        open={settingsOpen}
        config={config}
        onClose={() => setSettingsOpen(false)}
        onSaved={(nextConfig) => {
          setConfig(nextConfig);
          setMessage('设置已保存');
        }}
      />
    </main>
  );
}
