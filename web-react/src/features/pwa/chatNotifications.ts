import { jsonRequest } from '../../api/client';

export interface NotificationSettings {
  configured: boolean;
  public_key: string;
  reason?: string;
  devices: Array<{ id: string; enabled: number; last_error?: string }>;
}

export const notificationSettings = () => jsonRequest<NotificationSettings>('/api/chat-notifications');

export async function enableChatNotifications(settings: NotificationSettings) {
  if (!settings.configured) throw new Error(settings.reason || '服务器尚未完成推送配置。');
  // Permission must be requested directly from the user's click, before other awaits.
  const permission = await window.Notification.requestPermission();
  if (permission !== 'granted') throw new Error('尚未允许通知。你可以在系统通知设置中调整。');
  const reg = await window.navigator.serviceWorker.getRegistration('/');
  if (!reg?.active) throw new Error('应用尚未就绪，请在正式 HTTPS 站点重新打开后重试。');
  const encoded = settings.public_key.replace(/-/g, '+').replace(/_/g, '/');
  const key = Uint8Array.from(window.atob(encoded + '='.repeat((4 - encoded.length % 4) % 4)), char => char.charCodeAt(0));
  const subscription = await reg.pushManager.getSubscription() || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  await jsonRequest('/api/chat-notifications/subscribe', { method: 'POST', body: JSON.stringify({ subscription: subscription.toJSON() }) });
}

export async function disableChatNotifications() {
  const reg = await window.navigator.serviceWorker?.getRegistration('/');
  const subscription = await reg?.pushManager?.getSubscription();
  await jsonRequest('/api/chat-notifications/disable', { method: 'POST', body: JSON.stringify({ endpoint: subscription?.endpoint }) });
  await subscription?.unsubscribe();
  reg?.active?.postMessage({ type: 'CLEAR_CHAT_NOTIFICATIONS' });
}

export async function clearLocalPush() {
  if (!('serviceWorker' in window.navigator)) return;
  const reg = await window.navigator.serviceWorker.getRegistration('/');
  const subscription = await reg?.pushManager?.getSubscription();
  reg?.active?.postMessage({ type: 'CLEAR_CHAT_NOTIFICATIONS' });
  await subscription?.unsubscribe();
}
