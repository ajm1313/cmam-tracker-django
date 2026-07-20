/* CMAM Tracker Service Worker
 * Strategy:
 *  - Navigation requests: Network-first, fallback to cached page shell
 *  - Static assets (CSS/JS/img): Stale-while-revalidate
 *  - API GET requests: Network-first with cache fallback
 *  - Form POSTs: When network fails, pass to offline queue (IndexedDB)
 */

const CACHE_VERSION = 'cmam-v1.3.0';
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

// ── INSTALL: precache key assets ──────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

// ── ACTIVATE: clean old caches ─────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((k) => k.startsWith('cmam-') && k !== CACHE_VERSION && !k.endsWith('-static') && !k.endsWith('-pages') || (k.startsWith('cmam-') && k !== STATIC_CACHE && k !== PAGE_CACHE))
          .map((k) => caches.delete(k))
      ))
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

// ── Navigation: network-first with cache fallback ──────────────────────────
async function handleNavigation(request) {
  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.ok) {
      const cache = await caches.open(PAGE_CACHE);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (err) {
    // Try cache
    const cached = await caches.match(request);
    if (cached) return cached;

    // Try any cached page as fallback
    const pageCache = await caches.open(PAGE_CACHE);
    const keys = await pageCache.keys();
    if (keys.length > 0) {
      // Return the most recent cached page (better than offline page)
      const cachedPage = await pageCache.match(keys[keys.length - 1]);
      if (cachedPage) return cachedPage;
    }

    // Offline fallback page
    const offlineCache = await caches.open(STATIC_CACHE);
    const offlinePage = await offlineCache.match(OFFLINE_URL);
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

      if (response.ok || response.status === 302) {
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
