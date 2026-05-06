// Smart Home Service Worker
// Strategy:
//  - static assets (icons, css, js, fonts) -> cache-first
//  - HTML pages          -> network-first with cache fallback (so kontroly jsou vždy live)
//  - websocket / API     -> bypass

const CACHE_VERSION = 'smarthome-v4';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;

const PRECACHE = [
  '/',
  '/static/style.css',
  '/static/script.js',
  '/static/home.svg',
  '/static/heating.svg',
  '/static/solar.svg',
  '/static/light.svg',
  '/static/camera.svg',
  '/static/alarm.svg',
  '/static/blinds.svg',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/manifest.json',
  '/static/hp_settings_client.js',
  '/static/blinds_client.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => !k.startsWith(CACHE_VERSION))
            .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Bypass non-cacheable endpoints
  if (url.pathname.startsWith('/websocket') ||
      url.pathname.startsWith('/sensor') ||
      url.pathname.startsWith('/ping') ||
      url.pathname.startsWith('/stove') ||
      url.pathname.startsWith('/roomsList')) {
    return;
  }

  // Static assets -> cache first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((cached) =>
        cached || fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(STATIC_CACHE).then((c) => c.put(req, copy));
          return res;
        })
      )
    );
    return;
  }

  // HTML pages -> network first, fallback to cache
  event.respondWith(
    fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(PAGE_CACHE).then((c) => c.put(req, copy));
      return res;
    }).catch(() => caches.match(req).then((c) => c || caches.match('/')))
  );
});
