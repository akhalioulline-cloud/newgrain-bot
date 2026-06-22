/* Flagleaf PWA service worker — Phase A (installable + offline shell).
 * Strategy:
 *   - /api/*  → always network (never cached here; offline upload queue comes in Phase C).
 *   - navigations → network-first, fall back to the cached app shell when offline.
 *   - other GETs (icons, fonts, css) → cache-first, then network (and cache it).
 * Bump CACHE to ship a new shell; old caches are pruned on activate.
 */
const CACHE = 'flagleaf-shell-v2';
const SHELL = [
  '/app/',
  '/app/index.html',
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

  if (req.mode === 'navigate') {                          // page loads: fresh if online, shell if not
    e.respondWith(fetch(req).catch(() => caches.match('/app/index.html')));
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
