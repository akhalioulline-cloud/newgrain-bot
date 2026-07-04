/* Flagleaf PWA service worker — Phase A (installable + offline shell).
 * Strategy:
 *   - /api/*  → always network (never cached here; offline upload queue comes in Phase C).
 *   - navigations → network-first, fall back to the cached app shell when offline.
 *   - other GETs (icons, fonts, css) → cache-first, then network (and cache it).
 * Bump CACHE to ship a new shell; old caches are pruned on activate.
 */
const CACHE = 'flagleaf-shell-v43';
const SHELL = [
  '/app/',
  '/app/index.html',
  '/app/assistant.html',
  '/app/review.html',
  '/app/scan.html',
  '/app/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  '/apple-touch-icon.png',
  '/favicon.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;                       // uploads/posts: let them hit the network
  const url = new URL(req.url);
  if (url.pathname.startsWith('/api/')) return;           // API is always live

  if (req.mode === 'navigate') {                          // page loads: fresh if online, cached tab if not
    e.respondWith(
      fetch(req).catch(() => caches.match(req).then((c) => c || caches.match('/app/index.html')))
    );
    return;
  }

  e.respondWith((async () => {
    const cached = await caches.match(req);
    if (cached) return cached;
    try {
      const res = await fetch(req);
      const cacheable = res.ok && (
        url.origin === location.origin ||
        url.hostname.endsWith('gstatic.com') ||
        url.hostname.endsWith('googleapis.com')
      );
      if (cacheable) {
        const c = await caches.open(CACHE);
        c.put(req, res.clone());
      }
      return res;
    } catch (err) {
      return cached || Response.error();
    }
  })());
});

/* ---- Web Push ---- */
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data.json(); } catch (_) { d = { body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || 'Flagleaf', {
    body: d.body || '',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { url: d.url || '/app/' }
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || '/app/';
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if (c.url.includes('/app') && 'focus' in c) return c.focus();
      }
      return self.clients.openWindow(target);
    })
  );
});

/* ---- Background Sync (Android) ---- when signal returns the OS wakes us even if the app is
 * closed. We don't upload from here (no session token in the SW, and we'd risk double-sends);
 * instead: if a page is open, tell it to flush; otherwise nudge the user to reopen. */
function pendingCount() {
  return new Promise((res) => {
    let done = (n) => { done = () => {}; res(n); };
    try {
      const r = indexedDB.open('flagleaf-q', 1);
      r.onsuccess = () => {
        try {
          const cq = r.result.transaction('q', 'readonly').objectStore('q').count();
          cq.onsuccess = () => done(cq.result || 0);
          cq.onerror = () => done(0);
        } catch (_) { done(0); }
      };
      r.onerror = () => done(0);
    } catch (_) { done(0); }
  });
}

self.addEventListener('sync', (e) => {
  if (e.tag !== 'flagleaf-flush') return;
  e.waitUntil((async () => {
    const clientsList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    if (clientsList.length) { clientsList.forEach((c) => c.postMessage({ type: 'flush' })); return; }
    const n = await pendingCount();
    if (n > 0 && self.registration.showNotification) {
      await self.registration.showNotification('Flagleaf', {
        body: `📤 ${n} ${n === 1 ? 'кадр ждёт' : 'кадров ждут'} отправки — откройте, чтобы отправить.`,
        icon: '/icon-192.png', badge: '/icon-192.png', tag: 'flagleaf-flush',
        data: { url: '/app/' }
      });
    }
  })());
});
