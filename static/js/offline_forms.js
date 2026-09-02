/* CMAM Tracker offline form queue.
 * Only forms explicitly marked data-offline-capable are stored.
 */
(function () {
  'use strict';

  const DB_NAME = 'cmam_offline';
  const DB_VERSION = 2;
  const STORE = 'pendingSubmissions';
  let directSyncPromise = null;

  function ownerId() {
    const current = document.body?.dataset.userId || '';
    if (current) localStorage.setItem('cmam_active_user', current);
    return current || localStorage.getItem('cmam_active_user') || '';
  }

  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 3) | 8).toString(16);
    });
  }

  function openDB() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains('metadata')) db.createObjectStore('metadata', { keyPath: 'key' });
        let store;
        if (!db.objectStoreNames.contains(STORE)) {
          store = db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
        } else {
          store = request.transaction.objectStore(STORE);
        }
        if (!store.indexNames.contains('timestamp')) store.createIndex('timestamp', 'timestamp');
        if (!store.indexNames.contains('ownerId')) store.createIndex('ownerId', 'ownerId');
        if (!store.indexNames.contains('state')) store.createIndex('state', 'state');
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  function transaction(mode, action) {
    return openDB().then((db) => new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const store = tx.objectStore(STORE);
      let result;
      try { result = action(store); } catch (error) { reject(error); return; }
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    }));
  }

  function requestResult(request, fallback) {
    return new Promise((resolve) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(fallback);
    });
  }

  async function allItems() {
    const db = await openDB();
    return requestResult(db.transaction(STORE, 'readonly').objectStore(STORE).getAll(), []);
  }

  async function putItem(item) {
    const db = await openDB();
    return requestResult(db.transaction(STORE, 'readwrite').objectStore(STORE).put(item));
  }

  async function deleteItem(id) {
    return transaction('readwrite', (store) => store.delete(id));
  }

  function currentItems(items) {
    const owner = ownerId();
    return items.filter((item) => !item.ownerId || item.ownerId === owner);
  }

  function ensureOfflineIdentity(form) {
    let uid = form.querySelector('[name="client_uid"]');
    if (!uid) {
      uid = document.createElement('input');
      uid.type = 'hidden';
      uid.name = 'client_uid';
      form.appendChild(uid);
    }
    if (!uid.value) uid.value = uuid();

    let owner = form.querySelector('[name="_offline_owner_id"]');
    if (!owner) {
      owner = document.createElement('input');
      owner.type = 'hidden';
      owner.name = '_offline_owner_id';
      form.appendChild(owner);
    }
    owner.value = ownerId();
    return uid.value;
  }

  function fieldsFromFormData(formData) {
    const fields = [];
    const files = [];
    for (const [key, value] of formData.entries()) {
      if (value instanceof File) {
        if (value.name || value.size) files.push({ key, file: value, name: value.name });
      } else {
        fields.push([key, value]);
      }
    }
    return { fields, files };
  }

  async function queueForm(form) {
    const clientUid = ensureOfflineIdentity(form);
    const formData = new FormData(form);
    const { fields, files } = fieldsFromFormData(formData);
    const item = {
      url: form.action || location.href,
      method: (form.method || 'POST').toUpperCase(),
      fields,
      files,
      ownerId: ownerId(),
      clientUid,
      kind: form.dataset.offlineKind || 'form',
      timestamp: Date.now(),
      retries: 0,
      state: 'queued',
      lastError: '',
    };
    const db = await openDB();
    item.id = await requestResult(
      db.transaction(STORE, 'readwrite').objectStore(STORE).add(item),
      null
    );
    if (item.id === null) throw new Error('The offline record could not be saved.');
    await registerBackgroundSync();
    return item;
  }

  function rebuildFormData(item) {
    const formData = new FormData();
    const fields = item.fields || Object.entries(item.data || {});
    for (const [key, value] of fields) formData.append(key, value);
    for (const stored of item.files || []) {
      if (stored.file instanceof Blob) {
        formData.append(stored.key, stored.file, stored.name || stored.file.name || 'upload');
      } else if (stored.base64) {
        const [header, encoded] = stored.base64.split(',');
        const mime = (header.match(/:(.*?);/) || [])[1] || stored.type || 'application/octet-stream';
        const binary = atob(encoded);
        const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
        formData.append(stored.key, new Blob([bytes], { type: mime }), stored.name || 'upload');
      }
    }
    return formData;
  }

  async function parseResult(response) {
    const type = response.headers.get('content-type') || '';
    if (!type.includes('application/json')) {
      return { success: false, error: response.redirected ? 'Please sign in again before syncing.' : 'The server returned an unexpected response.' };
    }
    const result = await response.json().catch(() => ({}));
    return {
      success: response.ok && result.success === true,
      error: result.error || result.message || `Server error (${response.status})`,
      payload: result,
    };
  }

  async function rewriteDependentVisits(clientUid, serverId) {
    if (!clientUid || !serverId) return;
    const pendingPath = `/manage/visits/client/${clientUid}/record/`;
    for (const item of await allItems()) {
      if (new URL(item.url, location.origin).pathname === pendingPath) {
        item.url = new URL(`/manage/visits/${serverId}/record/`, location.origin).href;
        await putItem(item);
      }
    }
  }

  async function directSync() {
    if (directSyncPromise) return directSyncPromise;
    directSyncPromise = (async () => {
      let synced = 0;
      let failed = 0;
      for (const snapshot of currentItems(await allItems())) {
        const item = (await allItems()).find((candidate) => candidate.id === snapshot.id) || snapshot;
        if (item.state === 'failed') { failed += 1; continue; }
        try {
          const response = await fetch(item.url, {
            method: item.method || 'POST',
            body: rebuildFormData(item),
            credentials: 'same-origin',
            headers: { 'X-Offline-Sync': '1' },
          });
          const result = await parseResult(response);
          if (result.success) {
            if (item.kind === 'case') await rewriteDependentVisits(item.clientUid, result.payload?.data?.id);
            await deleteItem(item.id);
            synced += 1;
          } else if (response.status === 401 || response.status === 403 || response.redirected || response.status >= 500) {
            item.state = 'queued';
            item.lastError = result.error;
            item.retries = (item.retries || 0) + 1;
            await putItem(item);
            failed += 1;
          } else {
            item.state = 'failed';
            item.lastError = result.error;
            await putItem(item);
            failed += 1;
          }
        } catch (error) {
          item.state = 'queued';
          item.lastError = error.message || 'No internet connection.';
          item.retries = (item.retries || 0) + 1;
          await putItem(item);
          failed += 1;
        }
      }
      announceResult(synced, failed);
      return { synced, failed };
    })().finally(() => { directSyncPromise = null; });
    return directSyncPromise;
  }

  async function registerBackgroundSync() {
    if (!('serviceWorker' in navigator)) return;
    try {
      const registration = await navigator.serviceWorker.ready;
      if ('sync' in registration) await registration.sync.register('cmam-sync');
    } catch (_) { /* Online/page events remain as a fallback. */ }
  }

  async function messageWorker(type, extra) {
    if (!('serviceWorker' in navigator)) return false;
    try {
      const registration = await navigator.serviceWorker.ready;
      const worker = navigator.serviceWorker.controller || registration.active;
      if (!worker) return false;
      worker.postMessage(Object.assign({ type }, extra || {}));
      return true;
    } catch (_) { return false; }
  }

  function toast(message, error) {
    const element = document.createElement('div');
    element.textContent = message;
    element.style.cssText = `position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:999999;max-width:90vw;padding:12px 20px;border-radius:8px;color:white;text-align:center;background:${error ? '#dc2626' : '#059669'};box-shadow:0 4px 12px #0003`;
    document.body.appendChild(element);
    setTimeout(() => element.remove(), 4500);
  }

  function createBanner() {
    if (document.getElementById('offlineBanner')) return;
    const banner = document.createElement('button');
    banner.type = 'button';
    banner.id = 'offlineBanner';
    banner.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;z-index:99999;border:0;padding:8px 16px;color:white;text-align:center;background:#d97706;cursor:pointer';
    banner.addEventListener('click', showQueue);
    document.body.prepend(banner);
  }

  async function updateBanner() {
    const items = currentItems(await allItems());
    const failed = items.filter((item) => item.state === 'failed').length;
    const banner = document.getElementById('offlineBanner');
    if (!banner) return;
    window.cmamPendingCount = items.length;
    if (typeof window.updateSyncStatus === 'function') window.updateSyncStatus();
    if (!navigator.onLine || items.length) {
      banner.style.display = 'block';
      banner.style.background = failed ? '#dc2626' : (!navigator.onLine ? '#d97706' : '#2563eb');
      banner.textContent = `${navigator.onLine ? 'Online' : 'Offline'} · ${items.length} pending${failed ? ` · ${failed} need attention` : ''} (tap to review)`;
      document.body.style.paddingTop = `${banner.offsetHeight}px`;
    } else {
      banner.style.display = 'none';
      document.body.style.paddingTop = '';
    }
  }

  async function showQueue() {
    document.getElementById('offlineQueueDialog')?.remove();
    const items = currentItems(await allItems());
    const dialog = document.createElement('div');
    dialog.id = 'offlineQueueDialog';
    dialog.style.cssText = 'position:fixed;inset:0;z-index:100000;background:#0007;display:flex;align-items:center;justify-content:center;padding:20px';
    const panel = document.createElement('div');
    panel.style.cssText = 'background:white;border-radius:12px;max-width:620px;width:100%;max-height:80vh;overflow:auto;padding:20px;color:#111827';
    panel.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center"><strong>Offline submissions (${items.length})</strong><button type="button" data-close style="font-size:24px;border:0;background:none">×</button></div>`;
    if (!items.length) panel.insertAdjacentHTML('beforeend', '<p>Nothing is waiting to sync.</p>');
    for (const item of items) {
      const row = document.createElement('div');
      row.style.cssText = 'border-top:1px solid #e5e7eb;padding:12px 0';
      row.innerHTML = `<div><strong>${item.kind === 'visit' ? 'Visit' : item.kind === 'case' ? 'Registration' : 'Form'}</strong> · ${new Date(item.timestamp).toLocaleString()}</div><div style="font-size:13px;color:${item.state === 'failed' ? '#b91c1c' : '#4b5563'}">${item.state || 'queued'}${item.lastError ? ` — ${item.lastError}` : ''}</div>`;
      const queuedType = (item.fields || []).find(([key]) => key === 'malnutrition_type')?.[1] || 'SAM';
      if (item.kind === 'case' && item.clientUid && queuedType !== 'IPC') {
        const link = document.createElement('a');
        link.href = `/manage/visits/client/${item.clientUid}/record/?type=${encodeURIComponent(queuedType)}`;
        link.textContent = 'Record a visit';
        link.style.cssText = 'margin-right:12px;color:#2563eb;font-size:13px';
        row.appendChild(link);
      }
      if (item.state === 'failed') {
        const retry = document.createElement('button');
        retry.type = 'button'; retry.textContent = 'Retry'; retry.style.cssText = 'margin-right:12px;color:#2563eb;border:0;background:none';
        retry.onclick = async () => { item.state = 'queued'; item.lastError = ''; await putItem(item); dialog.remove(); triggerSync(); };
        row.appendChild(retry);
      }
      const remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = 'Remove'; remove.style.cssText = 'color:#b91c1c;border:0;background:none';
      remove.onclick = async () => { if (confirm('Remove this unsynced submission?')) { await deleteItem(item.id); dialog.remove(); updateBanner(); } };
      row.appendChild(remove);
      panel.appendChild(row);
    }
    dialog.appendChild(panel);
    dialog.addEventListener('click', (event) => { if (event.target === dialog || event.target.dataset.close !== undefined) dialog.remove(); });
    document.body.appendChild(dialog);
  }

  function announceResult(synced, failed) {
    if (synced) toast(`${synced} offline submission${synced === 1 ? '' : 's'} synced.${failed ? ` ${failed} still need attention.` : ''}`);
    updateBanner();
  }

  async function triggerSync() {
    if (!navigator.onLine) { updateBanner(); return; }
    if (!await messageWorker('TRIGGER_SYNC', { ownerId: ownerId() })) await directSync();
  }

  function prepareForms() {
    document.querySelectorAll('form[data-offline-capable="true"]').forEach(ensureOfflineIdentity);
    document.addEventListener('submit', async (event) => {
      const form = event.target.closest?.('form[data-offline-capable="true"]');
      if (!form) return;
      ensureOfflineIdentity(form);
      if (navigator.onLine) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      try {
        const item = await queueForm(form);
        toast('Saved safely on this device. It will sync automatically.');
        if (item.kind === 'case') {
          const type = new FormData(form).get('malnutrition_type') || 'SAM';
          if (type !== 'IPC' && confirm('Registration saved offline. Record the first visit now?')) {
            location.href = `/manage/visits/client/${item.clientUid}/record/?type=${encodeURIComponent(type)}`;
          }
        }
        updateBanner();
      } catch (error) {
        toast(error.message || 'Could not save this form offline.', true);
      }
    }, true);
  }

  async function initialise() {
    createBanner();
    prepareForms();
    const visitUrls = Array.from(document.querySelectorAll('a[href]'))
      .map((link) => new URL(link.href, location.origin))
      .filter((url) => url.origin === location.origin && /^\/manage\/visits\/\d+\/record\/$/.test(url.pathname))
      .map((url) => url.pathname);
    await messageWorker('SET_ACTIVE_USER', {
      ownerId: ownerId(),
      csrfToken: (document.cookie.match(/(?:^|; )csrftoken=([^;]*)/) || [])[1] || '',
      urls: Array.from(new Set(['/dashboard/', '/manage/cases/', '/manage/cases/create/', '/manage/visits/', '/manage/ipc/', ...visitUrls])),
    });
    await updateBanner();
    if (navigator.onLine) triggerSync();
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', (event) => {
      if (event.data?.type === 'SYNC_COMPLETE') announceResult(event.data.synced || 0, event.data.failed || 0);
    });
  }
  window.addEventListener('online', triggerSync);
  window.addEventListener('offline', updateBanner);
  window.CMAMOffline = { sync: triggerSync, review: showQueue };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialise);
  else initialise();
})();
