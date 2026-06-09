// ═══════════════════════════════════════════════
// Andén.ar — Service Worker
// Estrategia: Cache-first para el HTML principal
// El archivo se cachea completo en la instalación
// ═══════════════════════════════════════════════

const CACHE_NAME = 'anden-ar-v2';
const ASSETS = [
  './',
  './index.html',
  'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&display=swap',
];

// Instalación: cachear assets críticos
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      // La fuente puede fallar offline, la ignoramos
      return cache.addAll(['./index.html']).catch(() => {});
    })
  );
  self.skipWaiting();
});

// Activación: borrar caches viejos
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// Fetch: cache-first para el HTML, network-first para fuentes
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Solo interceptamos GET
  if (e.request.method !== 'GET') return;

  // Fuentes de Google: network-first con fallback a cache
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    e.respondWith(
      fetch(e.request)
        .then(res => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
          return res;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Todo lo demás (el HTML principal): cache-first
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        }
        return res;
      });
    })
  );
});
