/* Minimal app-shell service worker for the Personal Knowledge Base PWA.
 * - Same-origin static assets: cache-first (offline shell works).
 * - /api and /uploads: network-first with cache fallback, short-lived.
 * Bump CACHE_VERSION to invalidate old caches.
 */
const CACHE_VERSION = 'kb-v1';
const STATIC_CACHE = `kb-static-${CACHE_VERSION}`;
const DATA_CACHE = `kb-data-${CACHE_VERSION}`;
const MAX_DATA_ENTRIES = 60;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(['/']))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => !k.startsWith(`kb-static-${CACHE_VERSION}`) && !k.startsWith(`kb-data-${CACHE_VERSION}`))
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

async function trimCache(name, max) {
  const cache = await caches.open(name);
  const keys = await cache.keys();
  if (keys.length > max) {
    await Promise.all(keys.slice(0, keys.length - max).map((k) => cache.delete(k)));
  }
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;

  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/uploads/')) {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(DATA_CACHE).then((cache) => cache.put(event.request, clone)).then(() => trimCache(DATA_CACHE, MAX_DATA_ENTRIES));
          }
          return res;
        })
        .catch(() => caches.match(event.request).then((hit) => hit || new Response('offline', { status: 503 })))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(
      (hit) =>
        hit ||
        fetch(event.request).then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(event.request, clone));
          }
          return res;
        })
    )
  );
});
