/* Static shell only. No API, attachment, journal, session or mutation caching. */
const CACHE = 'pocket-ally-shell-v2';
const SHELL = ['/static/offline.html','/static/style.css','/static/icon.svg','/static/icon-192.png','/static/icon-512.png','/static/manifest.webmanifest','/assets/companion-soft.png','/assets/companion-playful.png','/assets/companion-minimal.png'];
self.addEventListener('install', event => { event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener('activate', event => { event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('pocket-ally-shell-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  if (event.request.mode === 'navigate') { event.respondWith(fetch(event.request).catch(() => caches.match('/static/offline.html'))); return; }
  if (SHELL.includes(url.pathname) && !url.search) event.respondWith(fetch(event.request).catch(() => caches.match(url.pathname)));
});
