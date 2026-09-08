// Dedicated service worker for the wall-tablet PWA (/tablet.html).
// Deliberately minimal and isolated from the main site's service-worker.js
// so the standard home.karotka.cz install is untouched.
//
// It exists mainly to make /tablet.html installable as a fullscreen,
// landscape home-screen app. It ONLY handles navigations to the tablet
// page (network-first, cache fallback so the panel still shows if the
// server blips). Everything else — the /websocket JSON-RPC and the
// Frigate camera snapshots (a fresh cache-busted URL every 2 s) — is left
// to the browser's default handling, so nothing is cached unbounded.

const TABLET_CACHE = 'tablet-shell-v1';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== TABLET_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  // Only the tablet page itself; leave WS, Frigate, fonts, everything else
  // to the network so nothing accumulates in the cache.
  if (req.mode === 'navigate' && url.pathname === '/tablet.html') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(TABLET_CACHE).then((c) => c.put('/tablet.html', copy));
          return res;
        })
        .catch(() => caches.match('/tablet.html'))
    );
  }
});
