import { dehydrate, hydrate } from "@tanstack/react-query";

const STORAGE_KEY = "smart-watchlist-query-cache";
const MAX_AGE = 24 * 60 * 60 * 1000;

/**
 * Discards snapshots written by a different build. Without this, a deploy
 * that adds a field to a response replays the *old* shape out of IndexedDB
 * into code that now requires it: `useMe` holds its data with
 * `staleTime: Infinity`, so nothing ever refetches it, and every screen
 * downstream of the missing field renders a permanent skeleton. A hard
 * refresh does not help, because IndexedDB survives one.
 *
 * The cache is a load-time optimisation and nothing more, so throwing it
 * away on every deploy costs one refetch and removes the whole failure mode.
 */
const BUILD_ID = import.meta.env.VITE_BUILD_ID ?? "dev";

export async function restoreQueryCache(queryClient) {
  try {
    const serialized = await readCache();
    if (!serialized) return;
    const snapshot = JSON.parse(serialized);
    if (snapshot.buildId !== BUILD_ID) {
      await clearCache();
      return;
    }
    if (Date.now() - snapshot.timestamp > MAX_AGE) {
      await clearCache();
      return;
    }
    hydrate(queryClient, snapshot.clientState);
  } catch {
    // A snapshot we cannot read or parse is a snapshot we do not use. Start
    // from an empty cache rather than leaving the app wedged on stale state.
    await clearCache().catch(() => {});
  }
}

export async function persistQueryCache(queryClient) {
  const save = async () => {
    const snapshot = JSON.stringify({
      timestamp: Date.now(),
      buildId: BUILD_ID,
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

async function clearCache() {
  if (typeof indexedDB !== "undefined") {
    try {
      await idbWrite(null);
    } catch {
      // Fall through to localStorage below.
    }
  }
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Private browsing with storage disabled — nothing to clear.
  }
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
