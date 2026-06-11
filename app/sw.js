// ═══════════════════════════════════════════════════════════
// Andén.ar — Service Worker v3
//
// ESTRATEGIA: NETWORK-FIRST para todo.
//   · Online  → siempre baja la versión fresca del servidor
//               y actualiza el cache de fondo.
//   · Offline → sirve la última versión cacheada.
//
// Esto hace IMPOSIBLE que el SW sirva una versión vieja
// estando online (la causa del bug de pantalla negra de v2,
// que era cache-first).
//
// RESCATE AUTOMÁTICO: al activarse, borra todos los caches
// viejos (anden-ar-v1/v2) y recarga las pestañas abiertas
// una sola vez, para destrabar browsers que quedaron
// sirviendo la versión rota.
// ═══════════════════════════════════════════════════════════

const CACHE_NAME = 'anden-ar-v3';

// ── Instalación: precache best-effort y tomar control ya ──
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(['./index.html']).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

// ── Activación: limpiar caches viejos + rescate ──
self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    // ¿Había caches de versiones anteriores? (browsers brickeados por v2)
    const habiaViejos = keys.some(k => k !== CACHE_NAME);
    await Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)));
    await self.clients.claim();
    // Recarga única de pestañas abiertas SOLO si venimos de una versión vieja.
    // En una instalación limpia no hay caches viejos → no recarga nada.
    if (habiaViejos) {
      const clients = await self.clients.matchAll({ type: 'window' });
      for (const c of clients) {
        try { await c.navigate(c.url); } catch (err) { /* no-op */ }
      }
    }
  })());
});

// ── Fetch: network-first, fallback a cache ──
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;

  e.respondWith(
    fetch(e.request)
      .then(res => {
        // Cachear copia fresca (incluye fuentes cross-origin opacas)
        if (res && (res.ok || res.type === 'opaque')) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone)).catch(() => {});
        }
        return res;
      })
      .catch(() =>
        // Sin red: servir cache. Para navegaciones, fallback al index.
        caches.match(e.request).then(cached => {
          if (cached) return cached;
          if (e.request.mode === 'navigate') return caches.match('./index.html');
          return Response.error();
        })
      )
  );
});
