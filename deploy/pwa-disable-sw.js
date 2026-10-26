/* global self, caches */
// Emergency replacement for /sw.js. Close all site windows to allow activation.
// Never use skipWaiting here: running pages may contain drafts or active uploads.
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith('claw-home-')).map(name => caches.delete(name)));
    await self.registration.unregister();
  })());
});
