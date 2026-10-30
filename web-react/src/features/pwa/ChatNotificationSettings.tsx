import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { notificationSettings, enableChatNotifications, disableChatNotifications, type NotificationSettings } from './chatNotifications';

export function ChatNotificationSettings() {
  const [settings, setSettings] = useState<NotificationSettings>();
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const supported = window.isSecureContext && 'Notification' in window && 'serviceWorker' in window.navigator && 'PushManager' in window;
  const enabled = settings?.devices.some(device => device.enabled);
  useEffect(() => {
    void notificationSettings().then(setSettings).catch(() => setNotice('暂时无法读取通知设置，请稍后重新打开。'));
  }, []);
  const toggle = async () => {
    if (!settings || !supported || busy) return;
    setBusy(true); setNotice('');
    try {
      if (enabled) await disableChatNotifications();
      else await enableChatNotifications(settings);
      setSettings(await notificationSettings());
      setNotice(enabled ? '已关闭此登录设备的回复与家庭活动通知。' : '已开启。回复完成或家庭活动结束会通知你。');
    } catch (error) { setNotice((error as Error).message); }
    finally { setBusy(false); }
  };
  return <section className="chat-notification-settings" aria-label="回复与家庭活动通知">
    <h3>回复与家庭活动通知</h3>
    <p>回复完成或你创建的家庭活动结束时提醒你。锁屏通知不显示问题、回答或参与明细。</p>
    {!supported && <p>iPhone 请先<Link to="/install">添加到主屏幕</Link>，从桌面图标打开后开启通知。</p>}
    {settings && !settings.configured && <p role="status">回复与家庭活动通知暂不可用，请稍后重试或联系管理员。</p>}
    {settings?.devices.some(device => device.last_error) && <p role="status">上次通知未能送达。回复会保留在对话中；可以检查系统权限，或关闭后重新开启通知。</p>}
    <button type="button" disabled={!supported || !settings || (!enabled && !settings.configured) || busy} onClick={() => void toggle()}>{busy ? '正在处理…' : enabled ? '关闭回复与家庭活动通知' : '开启回复与家庭活动通知'}</button>
    {notice && <p role="status">{notice}</p>}
    <p className="home-muted">通知受网络、专注模式和系统设置影响；退出登录会停止此登录设备的后续推送。</p>
  </section>;
}
