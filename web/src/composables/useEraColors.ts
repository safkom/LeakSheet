/**
 * Shared reactive era color cache + ColorThief singleton.
 * Populated by EraCard after ColorThief extraction, consumed by ArtistView for search badges
 * and PlayerBar for dynamic accent coloring.
 *
 * Color extraction is serialized via a concurrency-limited queue (max 2)
 * to avoid frame drops from 20+ simultaneous canvas getImageData() calls.
 */
import { shallowRef, triggerRef } from 'vue'
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
// Color cache — plain Map (not reactive) + shallowRef version counter
// to avoid cascading Vue re-renders during initial load.
// ---------------------------------------------------------------------------

const _cache = new Map<string, EraColors>()
const _version = shallowRef(0)

export function setEraColors(eraName: string, colors: EraColors): void {
  _cache.set(eraName, colors)
  _version.value++
}

export function getEraColors(eraName: string): EraColors | null {
  // Reading _version.value creates a Vue dependency — consumers re-evaluate
  // when the version counter increments (i.e., when any era color is set).
  void _version.value
  return _cache.get(eraName) || null
}

// ---------------------------------------------------------------------------
// Concurrency-limited extraction queue — max 2 at a time
// ---------------------------------------------------------------------------

const _MAX_CONCURRENT = 2
let _running = 0
const _queue: Array<() => void> = []

function _dequeue(): void {
  while (_running < _MAX_CONCURRENT && _queue.length > 0) {
    _running++
    const task = _queue.shift()!
    // Run extraction in a rAF to yield to the browser between tasks
    requestAnimationFrame(() => {
      task()
      _running--
      _dequeue()
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
  } catch (e) {
    // ColorThief can fail on certain images — ignore
  }
}
