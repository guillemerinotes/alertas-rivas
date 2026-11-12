// RIV-Alert · service worker: permite instalar la app; siempre intenta la red primero.
const C = 'riv-alert-v1';
self.addEventListener('install', e => { e.waitUntil(caches.open(C).then(c => c.addAll(['/', '/icon.svg', '/manifest.webmanifest']))); self.skipWaiting(); });
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin || u.pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).then(r => { const copia = r.clone(); caches.open(C).then(c => c.put(e.request, copia)); return r; })
    .catch(() => caches.match(e.request)));
});
