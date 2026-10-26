/* global self */
import { precacheAndRoute, createHandlerBoundToURL } from 'workbox-precaching';
import { registerRoute, NavigationRoute } from 'workbox-routing';
import { clientsClaim, setCacheNameDetails } from 'workbox-core';

setCacheNameDetails({ prefix: 'claw-home', suffix: 'v1' });
// Build-time list contains public application files only. Never cache API/media responses.
precacheAndRoute(self.__WB_MANIFEST);
registerRoute(new NavigationRoute(createHandlerBoundToURL('/index.html'), {
  allowlist: [/^\/$/, /^\/(?:home|login|install|chat|sessions|settings|plugins|dashboard|admin)(?:\/|\?|$)/],
  denylist: [/^\/(?:api|files|generated)(?:\/|$)/],
}));
clientsClaim();

self.addEventListener('message', (event) => {
  if (event.data?.type !== 'APPLY_UPDATE') return;
  event.waitUntil((async () => {
    // A suspended tab cannot reliably acknowledge safety. Require it to be closed.
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const ok = windows.length === 1 && windows[0].id === event.source?.id;
    event.ports[0]?.postMessage({ ok });
    if (ok) await self.skipWaiting();
  })());
});

self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { title: '家庭提醒', body: event.data ? event.data.text() : '' };
  }

  const title = payload.title || '家庭提醒';
  const options = {
    body: payload.body || '',
    tag: payload.tag || payload.id || 'home-agent',
    data: { url: payload.url || '/home' },
    requireInteraction: Boolean(payload.requireInteraction),
    actions: [
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
        if ('focus' in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
