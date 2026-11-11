// limefx service worker.
// Page shell: served from the saved copy at once, refreshed in the background (the page is told when a
// newer one arrives). Static files: saved copy first. Live data (/api, /ws): never touched.
const VER = 'lfx-2';
const SHELL = ['/', '/static/pwa/icon-192.png', '/static/pwa/icon-512.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(VER).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VER).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  if (u.pathname.startsWith('/api/') || u.pathname.startsWith('/ws') || u.pathname.startsWith('/admin') || u.pathname === '/sw.js') return;
  if (e.request.mode === 'navigate' && u.pathname === '/') {
    e.respondWith(caches.open(VER).then(async c => {
      const cached = await c.match('/');
      const fresh = fetch('/', { cache: 'no-store' }).then(async r => {
        if (!r.ok) return r;
        const body = await r.clone().text();
        const old = cached ? await cached.clone().text() : null;
        await c.put('/', r.clone());
        if (old !== null && old !== body) (await self.clients.matchAll({ type: 'window' })).forEach(cl => cl.postMessage('lfx-update'));
        return r;
      }).catch(() => cached);
      if (cached) e.waitUntil(fresh.then(() => {}, () => {}));   // let the background refresh finish
      return cached || fresh;
    }));
    return;
  }
  if (u.pathname.startsWith('/static/')) {
    e.respondWith(caches.open(VER).then(async c => {
      const cached = await c.match(e.request);
      const fresh = fetch(e.request).then(r => { if (r.ok) c.put(e.request, r.clone()); return r; }).catch(() => cached);
      return cached || fresh;
    }));
  }
});
