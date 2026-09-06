import { dehydrate, hydrate } from "@tanstack/react-query";

const STORAGE_KEY = "smart-watchlist-query-cache";
const MAX_AGE = 24 * 60 * 60 * 1000;

export async function restoreQueryCache(queryClient) {
  const serialized = await readCache();
  if (!serialized) return;
  const snapshot = JSON.parse(serialized);
  if (Date.now() - snapshot.timestamp > MAX_AGE) return;
  hydrate(queryClient, snapshot.clientState);
}

export async function persistQueryCache(queryClient) {
  const save = async () => {
    const snapshot = JSON.stringify({
      timestamp: Date.now(),
      clientState: dehydrate(queryClient, { shouldDehydrateQuery: () => true }),
    });
    await writeCache(snapshot);
  };
  await save();
  return queryClient.getQueryCache().subscribe(() => {
    void save().catch((error) => {
      console.error("Query cache persistence unavailable", error);
    });
  });
}

async function readCache() {
  if (typeof indexedDB !== "undefined") {
    try {
      return await idbRead();
    } catch {
      // Storage fallback below is deliberate for private browsing and file-like hosts.
    }
  }
  return window.localStorage.getItem(STORAGE_KEY);
}

async function writeCache(value) {
  if (typeof indexedDB !== "undefined") {
    try {
      await idbWrite(value);
      return;
    } catch {
      // Storage fallback below is deliberate for private browsing and file-like hosts.
    }
  }
  window.localStorage.setItem(STORAGE_KEY, value);
}

function idbRead() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("smart-watchlist", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("query-cache");
    request.onsuccess = () => {
      const transaction = request.result.transaction("query-cache", "readonly");
      const read = transaction.objectStore("query-cache").get(STORAGE_KEY);
      read.onsuccess = () => resolve(read.result ?? null);
      read.onerror = () => reject(read.error);
    };
    request.onerror = () => reject(request.error);
  });
}

function idbWrite(value) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("smart-watchlist", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("query-cache");
    request.onsuccess = () => {
      const transaction = request.result.transaction("query-cache", "readwrite");
      transaction.objectStore("query-cache").put(value, STORAGE_KEY);
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
    };
    request.onerror = () => reject(request.error);
  });
}
