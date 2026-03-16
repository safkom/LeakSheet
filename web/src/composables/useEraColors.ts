/**
 * Shared reactive era color cache + ColorThief singleton.
 * Populated by EraCard after ColorThief extraction, consumed by ArtistView for search badges
 * and PlayerBar for dynamic accent coloring.
 *
 * Color extraction is serialized via a concurrency-limited queue (max 4)
 * to avoid frame drops from 20+ simultaneous canvas getImageData() calls.
 *
 * Extracted colors are persisted to localStorage so repeat visits skip
 * ColorThief entirely.
 */
import { shallowRef } from 'vue'
import ColorThief from 'colorthief'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EraColors {
  /** Background with low alpha, e.g. rgba(r,g,b,0.2) */
  bg: string
  /** Bright text color derived from dominant palette entry */
  text: string
  /** Border color with medium alpha */
  border: string
  /** Accent color for player controls, progress bars, etc. */
  accent: string
}

// ---------------------------------------------------------------------------
// Singleton ColorThief — stateless utility, one instance for the entire app
// ---------------------------------------------------------------------------

let _colorThief: ColorThief | null = null

export function getColorThief(): ColorThief {
  if (!_colorThief) _colorThief = new ColorThief()
  return _colorThief
}

// ---------------------------------------------------------------------------
// localStorage persistence — cache colors across sessions
// ---------------------------------------------------------------------------

const _LS_KEY = 'leaksheet-era-colors'
const _LS_MAX_ENTRIES = 200

function _loadFromStorage(): Map<string, EraColors> {
  try {
    const raw = localStorage.getItem(_LS_KEY)
    if (!raw) return new Map()
    const parsed = JSON.parse(raw) as Record<string, EraColors>
    return new Map(Object.entries(parsed))
  } catch {
    return new Map()
  }
}

function _saveToStorage(cache: Map<string, EraColors>): void {
  try {
    // Cap entries to prevent unbounded growth
    const entries = [...cache.entries()]
    const trimmed = entries.length > _LS_MAX_ENTRIES
      ? entries.slice(entries.length - _LS_MAX_ENTRIES)
      : entries
    localStorage.setItem(_LS_KEY, JSON.stringify(Object.fromEntries(trimmed)))
  } catch {
    // localStorage full or unavailable — ignore
  }
}

// ---------------------------------------------------------------------------
// Color cache — plain Map (not reactive) + shallowRef version counter
// to avoid cascading Vue re-renders during initial load.
// Initialized from localStorage on module load.
// ---------------------------------------------------------------------------

const _cache = _loadFromStorage()
const _version = shallowRef(0)

let _saveTimer: ReturnType<typeof setTimeout> | null = null

export function setEraColors(eraName: string, colors: EraColors): void {
  _cache.set(eraName, colors)
  _version.value++
  // Debounce localStorage writes — many eras extract in rapid succession
  if (_saveTimer) clearTimeout(_saveTimer)
  _saveTimer = setTimeout(() => _saveToStorage(_cache), 500)
}

export function getEraColors(eraName: string): EraColors | null {
  // Reading _version.value creates a Vue dependency — consumers re-evaluate
  // when the version counter increments (i.e., when any era color is set).
  void _version.value
  return _cache.get(eraName) || null
}

// ---------------------------------------------------------------------------
// Concurrency-limited extraction queue — max 4 at a time
// (bottleneck is image network fetch, not CPU)
// ---------------------------------------------------------------------------

const _MAX_CONCURRENT = 4
let _running = 0
const _queue: Array<() => void> = []

function _dequeue(): void {
  while (_running < _MAX_CONCURRENT && _queue.length > 0) {
    _running++
    const task = _queue.shift()!
    // Run extraction in a rAF to yield to the browser between tasks
    requestAnimationFrame(() => {
      try {
        task()
      } catch (e) {
        console.error('[useEraColors] queue task threw:', e)
      } finally {
        _running--
        _dequeue()
      }
    })
  }
}

/**
 * Extract badge colors from a loaded image element and store in cache.
 * Shared between EraCard (on img load) and App.vue (on preload).
 * Queued to limit concurrency and avoid jank.
 */
export function extractAndCacheEraColors(eraName: string, imgElement: HTMLImageElement): void {
  if (_cache.has(eraName)) return
  _queue.push(() => _doExtract(eraName, imgElement))
  _dequeue()
}

function _doExtract(eraName: string, imgElement: HTMLImageElement): void {
  if (_cache.has(eraName)) return
  try {
    const ct = getColorThief()
    const pal = ct.getPalette(imgElement, 5)
    if (pal && pal.length >= 2) {
      const c1 = pal[0]
      const bright = `rgb(${Math.min(255, c1[0] + 60)}, ${Math.min(255, c1[1] + 60)}, ${Math.min(255, c1[2] + 60)})`
      setEraColors(eraName, {
        bg: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.2)`,
        text: bright,
        border: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.3)`,
        accent: bright,
      })
    }
  } catch {
    // ColorThief can fail on certain images — ignore
  }
}
