import {
  Bell,
  Check,
  Clock3,
  Home,
  PackagePlus,
  RefreshCw,
  ShoppingBasket,
  Trash2,
  Utensils,
  X,
} from 'lucide-react';
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { homeApi } from '../../api/home';
import type { HomeInventoryItem, HomeNotification, HomeReminder, HomeTaskSummary } from '../../api/types';
import { formatTime } from '../../utils/format';

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

const urlBase64ToUint8Array = (base64String: string) => {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
};

function Kpi({ label, value, icon: Icon }: { label: string; value: number | string; icon: typeof Home }) {
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
  const [items, setItems] = useState<HomeInventoryItem[]>([]);
  const [expiring, setExpiring] = useState<HomeInventoryItem[]>([]);
  const [reminders, setReminders] = useState<HomeReminder[]>([]);
  const [notifications, setNotifications] = useState<HomeNotification[]>([]);
  const [summary, setSummary] = useState<HomeTaskSummary | null>(null);
  const [pushConfigured, setPushConfigured] = useState(false);
  const [pushPermission, setPushPermission] = useState(
    typeof window.Notification === 'undefined' ? 'unsupported' : window.Notification.permission,
  );
  const [deviceCount, setDeviceCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const [itemDraft, setItemDraft] = useState({ name: '', quantity: '', unit: '个', expires_at: '', zone: '冷藏层' });
  const [reminderDraft, setReminderDraft] = useState({ title: '', raw_text: '' });

  useEffect(() => {
    document.body.classList.add('home-route');
    return () => {
      document.body.classList.remove('home-route');
    };
  }, []);

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
    setPushPermission(typeof window.Notification === 'undefined' ? 'unsupported' : window.Notification.permission);
  }, []);

  useEffect(() => {
    void load().catch((error) => setMessage(error.message || '读取家庭数据失败'));
  }, [load]);

  const todayReminders = useMemo(() => {
    const today = new Date().toDateString();
    return reminders.filter((item) => item.next_run_at && new Date(item.next_run_at).toDateString() === today && item.status !== 'cancelled');
  }, [reminders]);

  const lowStock = useMemo(
    () => items.filter((item) => item.status === 'low' || (typeof item.quantity === 'number' && item.quantity <= 1)),
    [items],
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

  return (
    <main className="home-shell">
      <header className="home-topbar">
        <div>
          <span className="home-kicker">Home Agent</span>
          <h1>家庭事务</h1>
        </div>
        <nav className="home-nav" aria-label="家庭页面导航">
          <Link to="/" className="home-nav-link">
            对话
          </Link>
          <Link to="/dashboard" className="home-nav-link">
            看板
          </Link>
          <button className="icon-button" type="button" title="刷新" onClick={() => void load()}>
            <RefreshCw size={18} />
          </button>
        </nav>
      </header>

      {message ? <pre className="home-message">{message}</pre> : null}

      <section className="home-command-board" aria-label="家庭事务概览">
        <article className="home-focus-card">
          <div>
            <span className="home-kicker">Today</span>
            <h2>{todayReminders.length} 个提醒待关注</h2>
            <p>{expiring.length} 项 3 天内到期，{lowStock.length} 项库存偏低。</p>
          </div>
          <div className="home-ops">
            <Kpi icon={Clock3} label="今日提醒" value={todayReminders.length} />
            <Kpi icon={Utensils} label="快过期" value={expiring.length} />
            <Kpi icon={ShoppingBasket} label="低库存" value={lowStock.length} />
            <Kpi icon={Bell} label="绑定设备" value={deviceCount} />
          </div>
        </article>

        <aside className="home-command-side">
          <div>
            <span>推送权限</span>
            <strong>{pushPermission}</strong>
          </div>
          <div>
            <span>VAPID</span>
            <strong>{pushConfigured ? '已配置' : '未配置'}</strong>
          </div>
        </aside>
      </section>

      <div className="home-workbench">
        <section className="home-section home-primary-pane">
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
                  <small>{item.category || '其他'} · {item.zone || '未分区'}</small>
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

        <aside className="home-context-rail">
          <section className="home-section">
            <div className="home-section-head">
              <div>
                <h2>提醒</h2>
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
                <article className="home-list-item" key={reminder.id}>
                  <div>
                    <strong>{reminder.title}</strong>
                    <small>{relativeRunTime(reminder.next_run_at)} · {statusLabel[reminder.status || ''] || reminder.status}</small>
                  </div>
                  <div className="row-actions">
                    <button type="button" title="完成" onClick={() => void homeApi.completeReminder(reminder.id).then(load)}>
                      <Check size={15} />
                    </button>
                    <button type="button" title="延后 10 分钟" onClick={() => void homeApi.snoozeReminder(reminder.id, 10).then(load)}>
                      <Clock3 size={15} />
                    </button>
                    <button type="button" title="取消" onClick={() => void homeApi.cancelReminder(reminder.id).then(load)}>
                      <X size={15} />
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="home-section">
            <div className="home-section-head">
              <div>
                <h2>推送设置</h2>
                <p>权限、设备和测试通知。</p>
              </div>
            </div>
            <div className="push-state">
              <span>浏览器权限</span>
              <strong>{pushPermission}</strong>
              <span>VAPID</span>
              <strong>{pushConfigured ? '已配置' : '未配置'}</strong>
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
            <div className="home-list compact">
              {notifications.slice(0, 6).map((notification) => (
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
        </aside>

        <section className="home-section home-insights-pane">
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
    </main>
  );
}
