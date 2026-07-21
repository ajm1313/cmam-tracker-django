/* CMAM Tracker — Offline Form Interception
 * 
 * This script works alongside the service worker to provide:
 * 1. Visual offline banner with pending sync count
 * 2. Form submission interception when offline (fallback if SW doesn't catch it)
 * 3. Auto-sync when connectivity returns
 * 4. Pending submission count badge
 */

(function () {
  'use strict';

  // ── IndexedDB helper ──────────────────────────────────────────────────
  const DB_NAME = 'cmam_offline';
  const DB_VERSION = 1;
  const STORE = 'pendingSubmissions';
  const MAX_RETRIES = 5;
  const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB limit for base64 storage

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains(STORE)) {
          const store = db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
          store.createIndex('timestamp', 'timestamp', { unique: false });
        }
      };
      req.onsuccess = (e) => resolve(e.target.result);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async function getPendingCount() {
    const db = await openDB();
    const tx = db.transaction(STORE, 'readonly');
    return new Promise((resolve) => {
      const req = tx.objectStore(STORE).count();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(0);
    });
  }

  async function getAllPending() {
    const db = await openDB();
    const tx = db.transaction(STORE, 'readonly');
    return new Promise((resolve) => {
      const req = tx.objectStore(STORE).getAll();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve([]);
    });
  }

  async function removePending(id) {
    const db = await openDB();
    const tx = db.transaction(STORE, 'readwrite');
    return new Promise((resolve) => {
      const req = tx.objectStore(STORE).delete(id);
      req.onsuccess = () => resolve();
      req.onerror = () => resolve();
    });
  }

  async function queueSubmission(form) {
    const formData = new FormData(form);
    const data = {};
    const files = [];

    for (const [key, value] of formData.entries()) {
      if (value instanceof File) {
        // Store file as base64 if small enough; skip large files with a warning
        if (value.size <= MAX_FILE_SIZE) {
          const base64 = await fileToBase64(value);
          files.push({
            key,
            name: value.name,
            type: value.type,
            size: value.size,
            base64: base64,
          });
        } else {
          // File too large for offline storage — record metadata only
          files.push({
            key,
            name: value.name,
            type: value.type,
            size: value.size,
            skipped: true,
          });
        }
      } else {
        data[key] = value;
      }
    }

    // Generate idempotency key from form data hash
    const idempotencyKey = generateIdempotencyKey(data, files, form.action || window.location.href);

    const item = {
      url: form.action || window.location.href,
      method: form.method.toUpperCase() || 'POST',
      data: data,
      files: files,
      csrfToken: data.csrfmiddlewaretoken || '',
      formId: form.id || '',
      timestamp: Date.now(),
      retries: 0,
      idempotencyKey: idempotencyKey,
    };

    const db = await openDB();
    const tx = db.transaction(STORE, 'readwrite');
    return new Promise((resolve, reject) => {
      const req = tx.objectStore(STORE).add(item);
      req.onsuccess = () => resolve(item);
      req.onerror = () => reject(req.error);
    });
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        // result is data URL: data:<type>;base64,<data>
        resolve(reader.result);
      };
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
  }

  function base64ToBlob(dataUrl) {
    const arr = dataUrl.split(',');
    const mime = arr[0].match(/:(.*?);/)[1];
    const bstr = atob(arr[1]);
    const u8 = new Uint8Array(bstr.length);
    for (let i = 0; i < bstr.length; i++) {
      u8[i] = bstr.charCodeAt(i);
    }
    return new Blob([u8], { type: mime });
  }

  function generateIdempotencyKey(data, files, url) {
    const fileKeys = files.map(f => f.name + f.size).join('|');
    const dataStr = JSON.stringify(data) + fileKeys + url;
    let hash = 0;
    for (let i = 0; i < dataStr.length; i++) {
      const char = dataStr.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return 'offline-' + Math.abs(hash).toString(36) + '-' + Date.now().toString(36);
  }

  // ── Sync pending submissions ──────────────────────────────────────────
  async function syncPending() {
    const items = await getAllPending();
    if (items.length === 0) {
      updateBanner();
      return;
    }

    showSyncingBanner(items.length);

    let synced = 0;
    let failed = 0;
    let authFailed = false;

    for (const item of items) {
      // Skip items that have exceeded max retries
      if (item.retries >= MAX_RETRIES) {
        failed++;
        continue;
      }

      try {
        const formData = new FormData();
        for (const [key, value] of Object.entries(item.data)) {
          formData.append(key, value);
        }

        // Reconstruct files from base64
        if (item.files && item.files.length > 0) {
          for (const file of item.files) {
            if (file.base64) {
              const blob = base64ToBlob(file.base64);
              formData.append(file.key, blob, file.name);
            } else if (file.skipped) {
              // File was too large to store offline — skip it
              console.warn(`File ${file.name} was too large to store offline and will not be synced.`);
            }
          }
        }

        // Add idempotency header if supported
        const headers = {};
        if (item.idempotencyKey) {
          headers['X-Idempotency-Key'] = item.idempotencyKey;
        }

        const response = await fetch(item.url, {
          method: item.method,
          body: formData,
          credentials: 'same-origin',
          redirect: 'manual',
          headers: headers,
        });

        // Check for auth redirect: Django redirects to login page with 302
        // An opaque redirect (status 0) could also be an auth redirect
        // We need to verify it's not a login redirect by checking the location
        if (response.status === 302 || response.type === 'opaqueredirect' || response.status === 0) {
          // Try to detect auth redirect by checking if the redirect target is a login page
          const redirectUrl = response.headers.get('Location') || '';
          if (redirectUrl.includes('/login') || redirectUrl.includes('/accounts/login') || redirectUrl.includes('next=')) {
            // Session expired — don't treat as success, don't remove from queue
            authFailed = true;
            item.retries = (item.retries || 0) + 1;
            await updatePendingItem(item);
            failed++;
            continue;
          }
          // Non-auth redirect — treat as success (form was processed)
          await removePending(item.id);
          synced++;
        } else if (response.ok) {
          // 200-299 — success
          await removePending(item.id);
          synced++;
        } else if (response.status === 401 || response.status === 403) {
          // Auth failure — session expired
          authFailed = true;
          item.retries = (item.retries || 0) + 1;
          await updatePendingItem(item);
          failed++;
        } else if (response.status >= 400 && response.status < 500) {
          // Client error — keep for review but don't retry
          failed++;
        } else {
          // Server error — increment retry and keep
          item.retries = (item.retries || 0) + 1;
          await updatePendingItem(item);
          failed++;
        }
      } catch (err) {
        // Network error — increment retry and keep
        item.retries = (item.retries || 0) + 1;
        await updatePendingItem(item);
        failed++;
      }
    }

    if (authFailed) {
      showAuthWarning();
    }

    // If any synced, reload to show updated data
    if (synced > 0) {
      showSyncResult(synced, failed);
      setTimeout(() => window.location.reload(), 1500);
    } else {
      updateBanner();
    }
  }

  async function updatePendingItem(item) {
    const db = await openDB();
    const tx = db.transaction(STORE, 'readwrite');
    return new Promise((resolve) => {
      const req = tx.objectStore(STORE).put(item);
      req.onsuccess = () => resolve();
      req.onerror = () => resolve();
    });
  }

  function showAuthWarning() {
    const banner = document.getElementById('offlineBanner');
    if (!banner) return;
    banner.style.background = '#ef4444';
    banner.style.display = 'block';
    banner.innerHTML = '<span>⚠ Session expired — some submissions could not sync. Please <a href="/login/" style="color:#fff;text-decoration:underline;">log in</a> again.</span>';
    document.body.style.paddingTop = banner.offsetHeight + 'px';
  }

  // ── UI: Offline banner ────────────────────────────────────────────────
  function createBanner() {
    if (document.getElementById('offlineBanner')) return;

    const banner = document.createElement('div');
    banner.id = 'offlineBanner';
    banner.style.cssText = `
      position: fixed; top: 0; left: 0; right: 0; z-index: 99999;
      padding: 8px 16px; text-align: center; font-size: 13px; font-weight: 500;
      color: #fff; background: #f59e0b; transition: all 0.3s ease;
      display: none; box-shadow: 0 2px 4px rgba(0,0,0,0.15);
    `;
    document.body.insertBefore(banner, document.body.firstChild);
  }

  function showOfflineBanner(pendingCount) {
    const banner = document.getElementById('offlineBanner');
    if (!banner) return;
    banner.style.display = 'block';
    banner.style.background = '#f59e0b';
    banner.innerHTML = `
      <span>⚠ You are offline</span>
      ${pendingCount > 0 ? `<span style="margin-left:8px;background:rgba(255,255,255,0.25);padding:2px 8px;border-radius:10px;">${pendingCount} pending</span>` : ''}
    `;
    // Push content down so banner doesn't overlap
    document.body.style.paddingTop = banner.offsetHeight + 'px';
  }

  function showOnlineBanner() {
    const banner = document.getElementById('offlineBanner');
    if (!banner) return;
    banner.style.background = '#10b981';
    banner.style.display = 'block';
    banner.innerHTML = '<span>✓ Back online — syncing...</span>';
  }

  function showSyncingBanner(count) {
    const banner = document.getElementById('offlineBanner');
    if (!banner) return;
    banner.style.background = '#3b82f6';
    banner.style.display = 'block';
    banner.innerHTML = `<span>⟳ Syncing ${count} pending submission(s)...</span>`;
  }

  function showSyncResult(synced, failed) {
    const banner = document.getElementById('offlineBanner');
    if (!banner) return;
    banner.style.background = '#10b981';
    banner.style.display = 'block';
    banner.innerHTML = `<span>✓ Synced ${synced} submission(s)${failed > 0 ? `, ${failed} failed` : ''}. Refreshing...</span>`;
  }

  function hideBanner() {
    const banner = document.getElementById('offlineBanner');
    if (!banner) return;
    banner.style.display = 'none';
    document.body.style.paddingTop = '0';
  }

  async function updateBanner() {
    const pending = await getPendingCount();
    window.cmamPendingCount = pending;
    // Update header sync indicator if present
    if (typeof updateSyncStatus === 'function') updateSyncStatus();

    if (!navigator.onLine) {
      showOfflineBanner(pending);
    } else if (pending > 0) {
      showOnlineBanner();
      // Auto-sync
      syncPending();
    } else {
      hideBanner();
    }
  }

  // ── Form interception ─────────────────────────────────────────────────
  function interceptForms() {
    document.addEventListener('submit', async function (e) {
      // If online, let the form submit normally
      if (navigator.onLine) return;

      // If the service worker already handled it, don't double-intercept
      if (e.target.dataset.offlineQueued === 'true') return;

      e.preventDefault();
      e.stopPropagation();

      const form = e.target;
      const submitBtn = form.querySelector('[type="submit"]');
      const originalText = submitBtn ? submitBtn.textContent : '';

      try {
        await queueSubmission(form);
        if (submitBtn) {
          submitBtn.textContent = '✓ Saved Offline';
          submitBtn.style.background = '#10b981';
          submitBtn.style.color = '#fff';
          submitBtn.disabled = true;
        }

        // Show toast
        showToast('Form saved offline. It will sync automatically when you reconnect.', 'success');

        // Update banner
        updateBanner();
      } catch (err) {
        showToast('Failed to save form offline. Please try again.', 'error');
        if (submitBtn) {
          submitBtn.textContent = originalText;
          submitBtn.disabled = false;
        }
      }
    }, true); // Use capture phase to intercept before SW
  }

  // ── Toast notification ────────────────────────────────────────────────
  function showToast(message, type) {
    const toast = document.createElement('div');
    toast.style.cssText = `
      position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
      padding: 12px 24px; border-radius: 8px; font-size: 14px; font-weight: 500;
      color: #fff; z-index: 999999; box-shadow: 0 4px 12px rgba(0,0,0,0.2);
      transition: opacity 0.3s ease; max-width: 90vw; text-align: center;
      background: ${type === 'error' ? '#ef4444' : '#10b981'};
    `;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  // ── Manual sync button ────────────────────────────────────────────────
  function addSyncButton() {
    // Check if already added
    if (document.getElementById('manualSyncBtn')) return;

    // Add to the sync indicator in the header
    const syncIndicator = document.getElementById('syncIndicator');
    if (!syncIndicator) return;

    // Add click handler to existing sync indicator
    syncIndicator.style.cursor = 'pointer';
    syncIndicator.title = 'Click to sync pending submissions';
    syncIndicator.addEventListener('click', async function () {
      const pending = await getPendingCount();
      if (pending === 0) {
        showToast('No pending submissions to sync.', 'info');
        return;
      }
      if (!navigator.onLine) {
        showToast('You are offline. Sync will happen automatically when you reconnect.', 'info');
        return;
      }
      syncPending();
    });
  }

  // ── Listen for SW messages ────────────────────────────────────────────
  navigator.serviceWorker.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SYNC_COMPLETE') {
      if (event.data.synced > 0) {
        showSyncResult(event.data.synced, event.data.failed);
        setTimeout(() => window.location.reload(), 1500);
      } else {
        updateBanner();
      }
    }
  });

  // ── Online/offline event listeners ────────────────────────────────────
  window.addEventListener('online', () => {
    showOnlineBanner();
    // Trigger sync via service worker
    if (navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage({ type: 'TRIGGER_SYNC' });
    }
    // Also sync directly (in case SW doesn't handle it)
    setTimeout(() => syncPending(), 500);
  });

  window.addEventListener('offline', () => {
    updateBanner();
  });

  // ── Initialize ────────────────────────────────────────────────────────
  function init() {
    createBanner();
    interceptForms();
    addSyncButton();
    updateBanner();

    // If online and there are pending items, auto-sync on page load
    if (navigator.onLine) {
      getPendingCount().then((count) => {
        if (count > 0) {
          syncPending();
        }
      });
    }
  }

  // Run when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
