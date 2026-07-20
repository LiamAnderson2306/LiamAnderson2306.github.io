const V = 'flowstate-v1';
const SHELL = ['./', './index.html', './manifest.webmanifest', './icon-180.png', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== V && k !== 'flowstate-fonts').map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;

  // Google Fonts: stale-while-revalidate so the app works offline after first load
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    e.respondWith(
      caches.open('flowstate-fonts').then(c =>
        c.match(e.request).then(hit => {
          const fresh = fetch(e.request).then(res => { if (res.ok) c.put(e.request, res.clone()); return res; }).catch(() => hit);
          return hit || fresh;
        })
      )
    );
    return;
  }

  if (url.origin !== location.origin) return;

  // App shell: network-first (so updates land), cache fallback (so offline works)
  if (e.request.mode === 'navigate' || url.pathname.endsWith('index.html')) {
    e.respondWith(
      fetch(e.request)
        .then(res => { const cp = res.clone(); caches.open(V).then(c => c.put('./index.html', cp)); return res; })
        .catch(() => caches.match('./index.html'))
    );
    return;
  }

  // Everything else (icons, manifest): cache-first
  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
    if (res.ok) { const cp = res.clone(); caches.open(V).then(c => c.put(e.request, cp)); }
    return res;
  })));
});
