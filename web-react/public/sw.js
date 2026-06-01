/* global self */
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
