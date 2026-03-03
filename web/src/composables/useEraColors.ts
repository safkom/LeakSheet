/**
 * Shared reactive era color cache + ColorThief singleton.
 * Populated by EraCard after ColorThief extraction, consumed by ArtistView for search badges
 * and PlayerBar for dynamic accent coloring.
 */
import { reactive } from 'vue'
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
// Color cache
// ---------------------------------------------------------------------------

const _cache: Record<string, EraColors> = reactive({})

export function setEraColors(eraName: string, colors: EraColors): void {
  _cache[eraName] = colors
}

export function getEraColors(eraName: string): EraColors | null {
  return _cache[eraName] || null
}

/**
 * Extract badge colors from a loaded image element and store in cache.
 * Shared between EraCard (on img load) and App.vue (on preload).
 * Uses the module-level ColorThief singleton — no need to pass one in.
 */
export function extractAndCacheEraColors(eraName: string, imgElement: HTMLImageElement): void {
  if (_cache[eraName]) return
  try {
    const ct = getColorThief()
    const pal = ct.getPalette(imgElement, 5)
    if (pal && pal.length >= 2) {
      const c1 = pal[0]
      const bright = `rgb(${Math.min(255, c1[0] + 60)}, ${Math.min(255, c1[1] + 60)}, ${Math.min(255, c1[2] + 60)})`
      _cache[eraName] = {
        bg: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.2)`,
        text: bright,
        border: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.3)`,
        accent: bright,
      }
    }
  } catch (e) {
    // ColorThief can fail on certain images — ignore
  }
}
