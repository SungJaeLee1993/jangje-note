const CACHE = "farrier-v6";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon-180.png", "icon-192.png", "icon-512.png", "exam/bank.json", "exam/9_1.jpg", "exam/9_2.jpg", "exam/9_3.jpg", "exam/9_4.jpg", "exam/10_2.png", "exam/10_3.png", "exam/10_4.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: "reload" }))))); self.skipWaiting(); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  // always try the network first, skipping the browser HTTP cache; fall back to cache when offline
  e.respondWith(fetch(req, { cache: "no-store" }).then(res => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); } return res; })
    .catch(() => caches.match(req).then(r => r || caches.match("index.html"))));
});
