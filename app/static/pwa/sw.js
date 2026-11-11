// limefx service worker — network first; cached shell only as an offline fallback.
const VER = 'lfx-1';
const SHELL = ['/', '/static/pwa/icon-192.png', '/static/pwa/icon-512.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(VER).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VER).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  if (u.pathname.startsWith('/api/') || u.pathname.startsWith('/ws')) return;   // live data: never cached
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok && (e.request.mode === 'navigate' || u.pathname.startsWith('/static/'))) { const cp = r.clone(); caches.open(VER).then(c => c.put(e.request, cp)); }
    return r;
  }).catch(() => caches.match(e.request).then(m => m || (e.request.mode === 'navigate' ? caches.match('/') : undefined))));
});
