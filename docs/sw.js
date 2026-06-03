/* Service worker — offline shell for the TH Investment dashboard.
   App shell + Chart.js (CDN, opaque) are cache-first; data.json / benchmark.json
   are network-first (fresh when online, cached fallback offline). */
const VERSION = "thw-v1";
const SHELL = [
  "./index.html", "./manifest.webmanifest",
  "./icon-192.png", "./icon-512.png", "./apple-touch-icon.png",
  "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js",
];
const DATA = ["data.json", "benchmark.json", "history.json"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c =>
    Promise.allSettled(SHELL.map(u => c.add(new Request(u, { mode: u.startsWith("http") ? "no-cors" : "same-origin" }))))
  ).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const isData = DATA.some(d => req.url.endsWith(d));
  if (isData) {
    // network-first for data, fall back to cache when offline
    e.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(VERSION).then(c => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req))
    );
  } else {
    // cache-first for the shell
    e.respondWith(
      caches.match(req).then(hit => hit || fetch(req).then(res => {
        const copy = res.clone();
        caches.open(VERSION).then(c => c.put(req, copy)).catch(() => {});
        return res;
      }).catch(() => caches.match("./index.html")))
    );
  }
});
