const CACHE_NAME = "land-underwriter-mobile-shell-v1";
const APP_SHELL = [
  new URL("./", self.location.href).toString(),
  new URL("./manifest.webmanifest", self.location.href).toString(),
  new URL("./panel/styles.css", self.location.href).toString(),
  new URL("./panel/app.js", self.location.href).toString(),
  new URL("./panel/assets/icon-192.png", self.location.href).toString(),
  new URL("./panel/assets/icon-512.png", self.location.href).toString(),
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }
  if (new URL(event.request.url).origin !== self.location.origin) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) {
        return cached;
      }
      return fetch(event.request).then((response) => {
        if (!response.ok) {
          return response;
        }
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      });
    })
  );
});
