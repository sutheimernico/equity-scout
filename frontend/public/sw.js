// Service worker for the equity-scout cockpit shell.
//
// Lives in public/ so Vite copies it byte-for-byte to dist/sw.js — no build plugin, no
// bundling, no vite-plugin-pwa. It must stay valid standalone JS the browser can execute
// straight off the server.
//
// Bump CACHE_VERSION whenever the caching logic or the precache list changes: activate()
// deletes every cache that isn't this version, so a bump is how already-installed workers
// pick up new behaviour on next load instead of running the old logic forever.
const CACHE_VERSION = "es-v1";

const PRECACHE_URLS = ["/", "/index.html", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      // skipWaiting: the owner reloading right after a deploy should get the new worker
      // immediately, not after every other open tab of the cockpit has been closed.
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key))),
      )
      // clients.claim: take control of already-open tabs so the offline fallback works on
      // the very first reload after install, not only on the second one.
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Same-origin GETs only. POST pitch decisions (buy/sell/dismiss/etc.) must always hit the
  // network — silently queuing a trade decision while offline and replaying it later would
  // let the owner act on stale prices without knowing it, so we never intercept writes.
  // Cross-origin requests (if any ever appear) are left alone for the same reason: we only
  // know how to reason about caching for this app's own routes.
  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(apiStaleWhileRevalidate(request));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(navigateNetworkFirst(request));
    return;
  }

  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(request));
    return;
  }
});

// /api/*: network first so the cockpit always shows live numbers when the backend is up.
// On a successful response we store a stamped COPY (never the response we hand back to the
// page) so a later offline hit can serve "the last known state" — and useFreshness can prove
// via /api/health, independently, that "last known" is in fact stale right now. A non-ok
// response (e.g. a transient 500) is never cached: poisoning the offline fallback with an
// error body would turn a blip into a permanent lie. Only on a network throw (machine off,
// DNS failure, etc.) do we fall back to whatever copy is cached; if there is none, rethrow so
// the caller sees the real failure instead of a silent undefined.
async function apiStaleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_VERSION);
  try {
    const response = await fetch(request);
    if (response.ok) {
      const body = await response.clone().blob();
      const stamped = new Response(body, {
        status: response.status,
        statusText: response.statusText,
        headers: new Headers(response.headers),
      });
      stamped.headers.set("x-sw-cached-at", new Date().toISOString());
      await cache.put(request, stamped);
    }
    return response;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
}

// Navigations (address bar entry, reload, deep link from Telegram): try the network first so
// the owner always gets the current app shell when it's reachable. On failure, fall back to
// the precached /index.html — a client-side router error page is still a page, whereas the
// browser's own offline error screen is a dead end the owner can't recover from without
// leaving the app.
async function navigateNetworkFirst(request) {
  try {
    return await fetch(request);
  } catch (err) {
    const cache = await caches.open(CACHE_VERSION);
    const cached = await cache.match("/index.html");
    if (cached) return cached;
    throw err;
  }
}

// /assets/* and /icons/*: Vite content-hashes asset filenames on every build, so a given URL
// never changes its content — safe to serve straight from cache without ever re-checking the
// network, and a lot faster than round-tripping for something that can't have changed.
async function cacheFirst(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
  }
  return response;
}
