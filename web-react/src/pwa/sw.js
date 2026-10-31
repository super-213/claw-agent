/* global self */
import { precacheAndRoute, createHandlerBoundToURL } from 'workbox-precaching';
import { registerRoute, NavigationRoute } from 'workbox-routing';
import { clientsClaim, setCacheNameDetails } from 'workbox-core';

setCacheNameDetails({ prefix: 'claw-home', suffix: 'v1' });
// Build-time list contains public application files only. Never cache API/media responses.
precacheAndRoute(self.__WB_MANIFEST);
registerRoute(new NavigationRoute(createHandlerBoundToURL('/index.html'), {
  allowlist: [/^\/$/, /^\/(?:home|offline|login|install|chat|sessions|settings|plugins|dashboard|admin)(?:\/|\?|$)/],
  denylist: [/^\/(?:api|files|generated)(?:\/|$)/],
}));
clientsClaim();

self.addEventListener('message', (event) => {
  if (event.data?.type === 'CLEAR_CHAT_NOTIFICATIONS') {
    event.waitUntil(self.registration.getNotifications().then(notices => {
      notices.filter(notice => notice.tag.startsWith('chat-') || notice.tag.startsWith('activity:')).forEach(notice => notice.close());
    }));
    return;
  }
  if (event.data?.type !== 'APPLY_UPDATE') return;
  event.waitUntil((async () => {
    try {
      await self.skipWaiting();
      event.ports[0]?.postMessage({ ok: true });
    } catch {
      event.ports[0]?.postMessage({ ok: false });
    }
  })());
});

self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { title: '家庭提醒', body: event.data ? event.data.text() : '' };
  }

  const chat = payload.kind === 'chat_result';
  const title = payload.title || (chat ? '回复已完成' : '家庭提醒');
  const target = typeof payload.url === 'string' && /^\/(?:sessions\/[a-zA-Z0-9_-]+|home(?:\/[^?#]*)?)(?:[?#].*)?$/.test(payload.url) ? payload.url : '/home';
  const options = {
    body: payload.body || '',
    tag: payload.tag || payload.id || 'home-agent',
    data: { url: target, job_id: payload.job_id },
    requireInteraction: Boolean(payload.requireInteraction),
    actions: chat || payload.kind === 'family_activity' ? [] : [
      { action: 'view', title: '查看' },
      { action: 'done', title: '完成' },
    ],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || '/home';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client && new self.URL(client.url).pathname === url.split('?')[0]) {
          return client.navigate(url).then(() => client.focus());
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
