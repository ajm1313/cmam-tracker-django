/* CMAM Tracker Service Worker v2
 * Strategy:
 *  - Navigation requests: Stale-while-revalidate (serve cached immediately, update in background)
 *  - Pre-fetch key app pages on activate so they're available offline
 *  - Static assets (CSS/JS/img): Stale-while-revalidate
 *  - API GET requests: Network-first with cache fallback
 *  - Form POSTs: When network fails, queue to IndexedDB for later sync
 */

const CACHE_VERSION = 'cmam-v2.1.0';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;
const OFFLINE_URL = '/offline/';

// Assets to precache on install
const PRECACHE_URLS = [
  '/offline/',
  '/static/js/offline_forms.js',
  '/static/js/sam_opc_automation.js',
  '/static/manifest.json',
];

// Main app pages to pre-fetch on activate (best-effort, failures ignored)
const APP_PAGES = [
  '/dashboard/',
  '/manage/cases/',
  '/manage/cases/dashboard/',
  '/manage/inventory/',
  '/manage/inventory/stock-levels/',
  '/manage/inventory/movements/',
  '/manage/inventory/requests/',
  '/manage/inventory/items/',
  '/manage/inventory/receive/',
  '/manage/inventory/distribute/',
  '/manage/visits/',
  '/manage/discharge/',
  '/manage/ipc/',
  '/manage/facilities/',
  '/manage/users/',
  '/reports/',
  '/locations/',
  '/locations/regions/',
  '/locations/districts/',
  '/locations/sub-districts/',
  '/profile/',
  '/settings/',
  '/manage/batch-visit/',
];

// ── INSTALL: precache key assets ──────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

// ── ACTIVATE: clean old caches + pre-fetch app pages ───────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((k) => k.startsWith('cmam-') && k !== STATIC_CACHE && k !== PAGE_CACHE)
          .map((k) => caches.delete(k))
      ))
      .then(() => {
        // Pre-fetch app pages in background (best-effort, ignore failures)
        caches.open(PAGE_CACHE).then((cache) => {
          APP_PAGES.forEach((url) => {
            fetch(url, { credentials: 'same-origin' })
              .then((resp) => {
                if (resp && resp.ok) cache.put(url, resp.clone());
              })
              .catch(() => {});
          });
        });
      })
      .then(() => self.clients.claim())
  );
});

// ── FETCH: routing strategy ────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only handle GET and POST
  if (request.method !== 'GET' && request.method !== 'POST') return;

  // Skip cross-origin requests
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Skip Chrome extension requests
  if (url.pathname.startsWith('/chrome-extension/')) return;

  // Skip Django admin
  if (url.pathname.startsWith('/admin/')) return;

  // ── POST requests (form submissions) ──
  if (request.method === 'POST') {
    event.respondWith(handlePost(event));
    return;
  }

  // ── GET requests ──
  // Navigation requests (HTML pages)
  if (request.mode === 'navigate') {
    event.respondWith(handleNavigation(request));
    return;
  }

  // Static assets
  if (url.pathname.startsWith('/static/') || /\.(?:css|js|png|jpg|jpeg|gif|svg|ico|woff2?)$/i.test(url.pathname)) {
    event.respondWith(staleWhileRevalidate(request, STATIC_CACHE));
    return;
  }

  // API GET requests
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request, STATIC_CACHE));
    return;
  }

  // Default: try network, fallback to cache
  event.respondWith(networkFirst(request, PAGE_CACHE));
});

// Pages that must never be served from cache (contain CSRF tokens or session state)
const NO_CACHE_PAGES = ['/login/', '/logout/', '/password-reset/', '/password-reset/done/'];

// ── Navigation: stale-while-revalidate ─────────────────────────────────────
// Serve cached page immediately if available, fetch updated version in background.
// If not cached, try network. If network fails too, show offline page.
// Auth pages are always fetched from network — cached CSRF tokens cause 403 errors.
async function handleNavigation(request) {
  const url = new URL(request.url);

  // Auth pages must always come from network
  if (NO_CACHE_PAGES.some((p) => url.pathname === p || url.pathname.startsWith(p))) {
    try {
      return await fetch(request, { credentials: 'same-origin' });
    } catch (err) {
      const staticCache = await caches.open(STATIC_CACHE);
      const offlinePage = await staticCache.match(OFFLINE_URL);
      if (offlinePage) return offlinePage;
      return new Response(
        '<html><body style="font-family:sans-serif;text-align:center;padding:40px"><h2>You are offline</h2><p>Please connect to the internet to log in.</p></body></html>',
        { headers: { 'Content-Type': 'text/html' } }
      );
    }
  }

  const cache = await caches.open(PAGE_CACHE);
  const cached = await cache.match(request);

  // If we have a cached version, serve it immediately and revalidate in background
  if (cached) {
    // Fire-and-forget background update
    fetch(request, { credentials: 'same-origin' })
      .then((response) => {
        if (response && response.ok) {
          cache.put(request, response.clone());
        }
      })
      .catch(() => {});
    return cached;
  }

  // No cached version — try network
  try {
    const networkResponse = await fetch(request, { credentials: 'same-origin' });
    if (networkResponse && networkResponse.ok) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (err) {
    // Try matching with ignoreSearch (in case of query params)
    const cachedFallback = await cache.match(request, { ignoreSearch: true });
    if (cachedFallback) return cachedFallback;

    // Try any cached page
    const keys = await cache.keys();
    if (keys.length > 0) {
      const cachedPage = await cache.match(keys[keys.length - 1]);
      if (cachedPage) return cachedPage;
    }

    // Offline fallback page
    const staticCache = await caches.open(STATIC_CACHE);
    const offlinePage = await staticCache.match(OFFLINE_URL);
    if (offlinePage) return offlinePage;

    return new Response(
      '<html><body style="font-family:sans-serif;text-align:center;padding:40px"><h2>You are offline</h2><p>The page will load automatically when you reconnect.</p></body></html>',
      { headers: { 'Content-Type': 'text/html' } }
    );
  }
}

// ── Stale-while-revalidate for static assets ───────────────────────────────
async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  const networkFetch = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => cached);

  return cached || networkFetch;
}

// ── Network-first with cache fallback ──────────────────────────────────────
async function networkFirst(request, cacheName) {
  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw err;
  }
}

// ── POST handler: try network, queue if offline ────────────────────────────
async function handlePost(event) {
  const { request } = event;
  const url = new URL(request.url);

  // Skip API POSTs (handled by fetch API from mobile app, not forms)
  if (url.pathname.startsWith('/api/')) {
    return fetch(request);
  }

  try {
    // Try to send the request normally
    const response = await fetch(request);
    return response;
  } catch (err) {
    // Network failed — clone the request body and queue it
    try {
      const formData = await request.clone().formData();
      const csrfToken = formData.get('csrfmiddlewaretoken') || '';

      // Convert FormData to a plain object
      const data = {};
      const files = [];
      for (const [key, value] of formData.entries()) {
        if (value instanceof File) {
          // Store file metadata (can't serialize File to IndexedDB easily)
          files.push({ key, name: value.name, type: value.type, size: value.size });
        } else {
          data[key] = value;
        }
      }

      const queueItem = {
        url: request.url,
        method: request.method,
        data: data,
        files: files,
        csrfToken: csrfToken,
        timestamp: Date.now(),
        retries: 0,
      };

      // Save to IndexedDB
      const db = await openDB();
      await db.put('pendingSubmissions', queueItem);

      // Return a synthetic "queued" response
      return new Response(
        JSON.stringify({ queued: true, message: 'Saved offline. Will sync when online.' }),
        {
          status: 202,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    } catch (queueErr) {
      // Can't even queue — return error
      return new Response(
        '<html><body style="font-family:sans-serif;text-align:center;padding:40px"><h2>Offline</h2><p>Your submission could not be saved. Please try again when online.</p></body></html>',
        { status: 503, headers: { 'Content-Type': 'text/html' } }
      );
    }
  }
}

// ── IndexedDB helper ───────────────────────────────────────────────────────
function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('cmam_offline', 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('pendingSubmissions')) {
        const store = db.createObjectStore('pendingSubmissions', { keyPath: 'id', autoIncrement: true });
        store.createIndex('timestamp', 'timestamp', { unique: false });
      }
    };
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror = (e) => reject(e.target.error);
  });
}

// ── Message handler: trigger sync from page ────────────────────────────────
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'TRIGGER_SYNC') {
    event.waitUntil(syncPendingSubmissions());
  }
});

// ── Background Sync API (if supported) ─────────────────────────────────────
self.addEventListener('sync', (event) => {
  if (event.tag === 'cmam-sync') {
    event.waitUntil(syncPendingSubmissions());
  }
});

// ── Sync pending submissions ───────────────────────────────────────────────
async function syncPendingSubmissions() {
  const db = await openDB();
  const tx = db.transaction('pendingSubmissions', 'readwrite');
  const store = tx.objectStore('pendingSubmissions');
  const allReq = store.getAll();
  const allItems = await new Promise((resolve, reject) => {
    allReq.onsuccess = () => resolve(allReq.result);
    allReq.onerror = () => reject(allReq.error);
  });

  let synced = 0;
  let failed = 0;

  for (const item of allItems) {
    try {
      // Build FormData from stored data
      const formData = new FormData();
      for (const [key, value] of Object.entries(item.data)) {
        formData.append(key, value);
      }

      const response = await fetch(item.url, {
        method: item.method,
        body: formData,
        credentials: 'same-origin',
      });

      if (response.ok || response.status === 302 || response.type === 'opaqueredirect') {
        // Success — remove from queue
        const delTx = db.transaction('pendingSubmissions', 'readwrite');
        await delTx.objectStore('pendingSubmissions').delete(item.id);
        synced++;
      } else if (response.status >= 400 && response.status < 500) {
        // Client error — don't retry, but keep for user review
        failed++;
      } else {
        // Server error — will retry on next sync
        failed++;
      }
    } catch (err) {
      failed++;
    }
  }

  // Notify clients about sync results
  const clients = await self.clients.matchAll();
  for (const client of clients) {
    client.postMessage({ type: 'SYNC_COMPLETE', synced, failed });
  }
}
