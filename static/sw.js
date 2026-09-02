/* CMAM Tracker service worker v3: private page cache + durable form outbox. */
const VERSION = 'cmam-v3.0.0';
const STATIC_CACHE = `${VERSION}-static`;
const PAGE_CACHE = `${VERSION}-pages`;
const OFFLINE_URL = '/offline/';
const OFFLINE_VISIT_URL = '/offline/visit/';
const DB_NAME = 'cmam_offline';
const DB_VERSION = 2;
const QUEUE = 'pendingSubmissions';
const META = 'metadata';
const AUTH_PATHS = ['/login/', '/logout/', '/password-reset/'];
const PRECACHE = [
  OFFLINE_URL,
  OFFLINE_VISIT_URL,
  '/static/js/offline_forms.js',
  '/static/js/sam_opc_automation.js',
  '/static/manifest.json',
];
let syncPromise = null;

function clientUuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
    const random = Math.random() * 16 | 0;
    return (character === 'x' ? random : (random & 3) | 8).toString(16);
  });
}

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(STATIC_CACHE)
    .then((cache) => cache.addAll(PRECACHE))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys
      .filter((key) => key.startsWith('cmam-') && key !== STATIC_CACHE && key !== PAGE_CACHE)
      .map((key) => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/admin/')) return;

  if (request.method === 'POST') {
    if (isOfflineFormPath(url.pathname)) event.respondWith(handlePost(request));
    return;
  }
  if (request.method !== 'GET') return;

  if (request.mode === 'navigate') {
    event.respondWith(navigate(request));
  } else if (url.pathname.startsWith('/static/') || url.pathname === '/sw.js') {
    event.respondWith(staleStatic(request));
  } else if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request));
  }
});

function isOfflineFormPath(path) {
  return path === '/manage/cases/create/' ||
    /^\/manage\/visits\/(?:\d+\/record|client\/[0-9a-f-]+\/record)\/$/i.test(path);
}

async function navigate(request) {
  const url = new URL(request.url);
  if (AUTH_PATHS.some((path) => url.pathname.startsWith(path))) {
    try {
      const response = await fetch(request);
      if (url.pathname.startsWith('/logout/')) {
        await caches.delete(PAGE_CACHE);
        await setMeta('activeOwner', '');
      }
      return response;
    } catch (_) { return offlineResponse(); }
  }

  const pageCache = await caches.open(PAGE_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok && !response.redirected) await pageCache.put(request, response.clone());
    return response;
  } catch (_) {
    const exact = await pageCache.match(request);
    if (exact) return exact;
    if (/^\/manage\/visits\/(?:\d+|client\/[0-9a-f-]+)\/record\/$/i.test(url.pathname)) {
      const visitForm = await caches.match(OFFLINE_VISIT_URL);
      if (visitForm) return visitForm;
    }
    return offlineResponse();
  }
}

async function offlineResponse() {
  return await caches.match(OFFLINE_URL) || new Response(
    '<!doctype html><html><body><h1>You are offline</h1><p>This page has not been saved on this device yet.</p></body></html>',
    { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
  );
}

async function staleStatic(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);
  const update = fetch(request).then((response) => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => cached);
  return cached || update;
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok && !response.redirected) {
      const cache = await caches.open(PAGE_CACHE);
      await cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw error;
  }
}

async function handlePost(request) {
  const backup = request.clone();
  try {
    return await fetch(request);
  } catch (_) {
    try {
      const formData = await backup.formData();
      const fields = [];
      const files = [];
      for (const [key, value] of formData.entries()) {
        if (value instanceof File) {
          if (value.name || value.size) files.push({ key, file: value, name: value.name });
        } else {
          fields.push([key, value]);
        }
      }
      const clientUid = String(formData.get('client_uid') || clientUuid());
      const item = {
        url: backup.url,
        method: 'POST',
        fields,
        files,
        ownerId: String(formData.get('_offline_owner_id') || await metaValue('activeOwner') || ''),
        clientUid,
        kind: new URL(backup.url).pathname === '/manage/cases/create/' ? 'case' : 'visit',
        timestamp: Date.now(),
        retries: 0,
        state: 'queued',
        lastError: '',
      };
      await addQueueItem(item);
      await requestBackgroundSync();
      return new Response(
        '<!doctype html><html><body style="font-family:sans-serif;padding:40px;text-align:center"><h2>Saved offline</h2><p>This submission is safely stored on this device and will sync automatically.</p><p><a href="/dashboard/">Return to dashboard</a></p></body></html>',
        { status: 202, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
      );
    } catch (queueError) {
      return new Response('The submission could not be saved offline.', { status: 503 });
    }
  }
}

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      let queue;
      if (!db.objectStoreNames.contains(QUEUE)) {
        queue = db.createObjectStore(QUEUE, { keyPath: 'id', autoIncrement: true });
      } else {
        queue = request.transaction.objectStore(QUEUE);
      }
      if (!queue.indexNames.contains('timestamp')) queue.createIndex('timestamp', 'timestamp');
      if (!queue.indexNames.contains('ownerId')) queue.createIndex('ownerId', 'ownerId');
      if (!queue.indexNames.contains('state')) queue.createIndex('state', 'state');
      if (!db.objectStoreNames.contains(META)) db.createObjectStore(META, { keyPath: 'key' });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function dbRequest(storeName, mode, operation) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, mode);
    const request = operation(tx.objectStore(storeName));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

const addQueueItem = (item) => dbRequest(QUEUE, 'readwrite', (store) => store.add(item));
const putQueueItem = (item) => dbRequest(QUEUE, 'readwrite', (store) => store.put(item));
const deleteQueueItem = (id) => dbRequest(QUEUE, 'readwrite', (store) => store.delete(id));
const allQueueItems = () => dbRequest(QUEUE, 'readonly', (store) => store.getAll());
const metaValue = async (key) => (await dbRequest(META, 'readonly', (store) => store.get(key)).catch(() => null))?.value;
const setMeta = (key, value) => dbRequest(META, 'readwrite', (store) => store.put({ key, value }));

async function requestBackgroundSync() {
  try {
    if (self.registration.sync) await self.registration.sync.register('cmam-sync');
  } catch (_) { /* Online and manual triggers remain available. */ }
}

function buildFormData(item, csrfToken) {
  const data = new FormData();
  const fields = item.fields || Object.entries(item.data || {});
  for (const [key, value] of fields) {
    if (key === 'csrfmiddlewaretoken' && csrfToken) data.append(key, csrfToken);
    else data.append(key, value);
  }
  if (csrfToken && !fields.some(([key]) => key === 'csrfmiddlewaretoken')) data.append('csrfmiddlewaretoken', csrfToken);
  for (const stored of item.files || []) {
    if (stored.file instanceof Blob) {
      data.append(stored.key, stored.file, stored.name || stored.file.name || 'upload');
    } else if (stored.base64) {
      const [header, encoded] = stored.base64.split(',');
      const mime = (header.match(/:(.*?);/) || [])[1] || stored.type || 'application/octet-stream';
      const binary = atob(encoded);
      const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
      data.append(stored.key, new Blob([bytes], { type: mime }), stored.name || 'upload');
    }
  }
  return data;
}

async function replayResult(response) {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    return { success: false, error: response.redirected ? 'Please sign in again before syncing.' : 'The server returned an unexpected response.' };
  }
  const payload = await response.json().catch(() => ({}));
  return {
    success: response.ok && payload.success === true,
    error: payload.error || payload.message || `Server error (${response.status})`,
    payload,
  };
}

async function rewriteDependentVisits(clientUid, serverId) {
  if (!clientUid || !serverId) return;
  const pendingPath = `/manage/visits/client/${clientUid}/record/`;
  for (const item of await allQueueItems()) {
    if (new URL(item.url, self.location.origin).pathname === pendingPath) {
      item.url = new URL(`/manage/visits/${serverId}/record/`, self.location.origin).href;
      await putQueueItem(item);
    }
  }
}

async function syncPendingSubmissions(ownerOverride) {
  if (syncPromise) return syncPromise;
  syncPromise = (async () => {
    const owner = ownerOverride || await metaValue('activeOwner') || '';
    const csrf = await metaValue('csrfToken') || '';
    let synced = 0;
    let failed = 0;
    for (const snapshot of await allQueueItems()) {
      const item = (await allQueueItems()).find((candidate) => candidate.id === snapshot.id) || snapshot;
      if (owner && item.ownerId && item.ownerId !== owner) continue;
      if (item.state === 'failed') { failed += 1; continue; }
      try {
        const response = await fetch(item.url, {
          method: item.method || 'POST',
          body: buildFormData(item, csrf),
          credentials: 'same-origin',
          headers: { 'X-Offline-Sync': '1' },
        });
        const result = await replayResult(response);
        if (result.success) {
          if (item.kind === 'case') await rewriteDependentVisits(item.clientUid, result.payload?.data?.id);
          await deleteQueueItem(item.id);
          synced += 1;
        } else if (response.status >= 500 || response.status === 401 || response.status === 403 || response.redirected) {
          item.state = 'queued';
          item.retries = (item.retries || 0) + 1;
          item.lastError = result.error;
          await putQueueItem(item);
          failed += 1;
        } else {
          item.state = 'failed';
          item.lastError = result.error;
          await putQueueItem(item);
          failed += 1;
        }
      } catch (error) {
        item.state = 'queued';
        item.retries = (item.retries || 0) + 1;
        item.lastError = error.message || 'No internet connection.';
        await putQueueItem(item);
        failed += 1;
      }
    }
    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    clients.forEach((client) => client.postMessage({ type: 'SYNC_COMPLETE', synced, failed }));
    return { synced, failed };
  })().finally(() => { syncPromise = null; });
  return syncPromise;
}

async function setActiveUser(data) {
  const previous = await metaValue('activeOwner') || '';
  const owner = String(data.ownerId || '');
  if (previous !== owner) await caches.delete(PAGE_CACHE);
  await setMeta('activeOwner', owner);
  if (data.csrfToken) await setMeta('csrfToken', data.csrfToken);
  if (!owner) return;

  // Assign pre-upgrade submissions once, then every new record is explicitly scoped.
  for (const item of await allQueueItems()) {
    if (!item.ownerId) { item.ownerId = owner; await putQueueItem(item); }
  }
  const cache = await caches.open(PAGE_CACHE);
  await Promise.all((data.urls || []).map(async (url) => {
    try {
      const response = await fetch(url, { credentials: 'same-origin' });
      if (response.ok && !response.redirected) await cache.put(url, response);
    } catch (_) { /* The exact page will be cached on a later successful visit. */ }
  }));
}

self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type === 'SKIP_WAITING') event.waitUntil(self.skipWaiting());
  if (data.type === 'TRIGGER_SYNC') event.waitUntil(syncPendingSubmissions(data.ownerId));
  if (data.type === 'SET_ACTIVE_USER') event.waitUntil(setActiveUser(data));
  if (data.type === 'CLEAR_PRIVATE_CACHE') event.waitUntil(caches.delete(PAGE_CACHE));
});

self.addEventListener('sync', (event) => {
  if (event.tag === 'cmam-sync') event.waitUntil(syncPendingSubmissions());
});
