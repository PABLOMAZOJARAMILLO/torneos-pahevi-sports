const CACHE_VERSION = 'pahevi-offline-v1';
const PRECACHE = ['/', '/?portal=1', '/ingresar/', '/manifest.webmanifest',
  '/static/torneos/img/icono-192.png', '/static/torneos/img/icono-512.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_VERSION)
    .then((cache) => Promise.allSettled(PRECACHE.map((url) => cache.add(url))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).then((response) => {
      if (response.ok) caches.open(CACHE_VERSION).then((cache) => cache.put(request, response.clone()));
      return response;
    }).catch(async () => (await caches.match(request)) || (await caches.match('/')) || new Response(
      '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Sin conexión</title><style>body{font-family:Arial;background:#07111f;color:white;padding:32px}h1{color:#00ff66}</style><h1>Sin conexión</h1><p>Abre nuevamente cuando vuelva la señal. Las páginas visitadas previamente quedan disponibles.</p>',
      {headers: {'Content-Type': 'text/html; charset=utf-8'}}
    )));
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request).then((response) => {
      if (response.ok) caches.open(CACHE_VERSION).then((cache) => cache.put(request, response.clone()));
      return response;
    })));
  }
});
