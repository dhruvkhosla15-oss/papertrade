// limefx service worker.
// Page shell: always fetched fresh; the saved copy is only a fallback when offline or the network is slow. Static files: saved copy first. Live data (/api, /ws): never touched.
const VER = 'lfx-3';
const SHELL = ['/', '/static/pwa/icon-192.png', '/static/pwa/icon-512.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(VER).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VER).map(k => caches.delete(k)))).then(() => self.clients.claim()).then(() => self.clients.matchAll({ type: 'window' })).then(cs => cs.forEach(cl => cl.postMessage('lfx-update')))); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  if (u.pathname.startsWith('/api/') || u.pathname.startsWith('/ws') || u.pathname.startsWith('/admin') || u.pathname === '/sw.js') return;
  if (e.request.mode === 'navigate' && u.pathname === '/') {
    // Network first (the server is close and the page is small), saved copy only when offline or slow.
    e.respondWith((async () => {
      const c = await caches.open(VER);
      const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), 4000);
      try {
        const r = await fetch('/', { cache: 'no-store', signal: ctl.signal });
        clearTimeout(timer);
        if (r.ok) c.put('/', r.clone()).catch(() => {});
        return r;
      } catch (err) {
        clearTimeout(timer);
        return (await c.match('/')) || fetch(e.request);
      }
    })());
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
