/**
 * Local IndexedDB cache for tracker data.
 *
 * Stores parsed Artist JSON + ETag keyed by tracker URL.
 * Used for instant rendering on return visits while the API validates freshness.
 */

const DB_NAME = 'leaksheet-cache'
const DB_VERSION = 1
const STORE = 'trackers'

export interface CachedTracker {
  url: string
  data: unknown
  etag: string
  timestamp: number
}

let _dbPromise: Promise<IDBDatabase> | null = null

function _openDB(): Promise<IDBDatabase> {
  if (_dbPromise) return _dbPromise
  _dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'url' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => {
      _dbPromise = null
      reject(req.error)
    }
  })
  return _dbPromise
}

/**
 * Retrieve cached tracker entry by URL, or null if not found.
 */
export async function getCachedTracker(url: string): Promise<CachedTracker | null> {
  try {
    const db = await _openDB()
    return new Promise((resolve) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).get(url)
      req.onsuccess = () => resolve(req.result ?? null)
      req.onerror = () => resolve(null)
    })
  } catch {
    return null
  }
}

/**
 * Store a tracker result with its ETag.
 */
export async function setCachedTracker(url: string, data: unknown, etag: string): Promise<void> {
  try {
    const db = await _openDB()
    return new Promise((resolve) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put({ url, data, etag, timestamp: Date.now() } satisfies CachedTracker)
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    })
  } catch {
    // Silently ignore (quota exceeded, etc.)
  }
}

/**
 * Clear all cached tracker data.
 */
export async function clearTrackerCache(): Promise<void> {
  try {
    const db = await _openDB()
    return new Promise((resolve) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).clear()
      tx.oncomplete = () => resolve()
      tx.onerror = () => resolve()
    })
  } catch {
    // Silently ignore
  }
}
