/* Minimal app-shell service worker for the Personal Knowledge Base PWA.
 * - Same-origin static assets: stale-while-revalidate (offline shell works,
 *   and a code change becomes visible after one reload instead of being
 *   cached forever — pure cache-first here meant a phone that had ever
 *   opened the app was stuck on whatever JS existed on its first visit
 *   until someone remembered to bump CACHE_VERSION by hand; confirmed on
 *   2026-09-12 as the cause of an iPad showing pre-fix Dashboard behavior).
 * - /api and /uploads: network-first with cache fallback, short-lived.
 * Bump CACHE_VERSION to force an immediate purge instead of waiting for the
 * background revalidation to catch up.
 */
const CACHE_VERSION = 'kb-v2';
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
    caches.match(event.request).then((hit) => {
      const network = fetch(event.request).then((res) => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(STATIC_CACHE).then((cache) => cache.put(event.request, clone));
        }
        return res;
      }).catch(() => null);
      // Serve the cached copy immediately when there is one (instant, works
      // offline), but always let the network fetch land in the cache too —
      // this load is one version behind at worst, not stuck forever.
      return hit || network;
    })
  );
});
