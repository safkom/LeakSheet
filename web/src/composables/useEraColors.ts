/**
 * Shared reactive era color cache.
 * Populated by EraCard after ColorThief extraction, consumed by ArtistView for search badges.
 */
import { reactive } from 'vue'

const _cache = reactive({})

export function setEraColors(eraName, colors) {
  _cache[eraName] = colors
}

export function getEraColors(eraName) {
  return _cache[eraName] || null
}

/**
 * Extract badge colors from a loaded image element and store in cache.
 * Shared between EraCard (on img load) and App.vue (on preload).
 */
export function extractAndCacheEraColors(eraName, imgElement, colorThief) {
  if (_cache[eraName]) return
  try {
    const pal = colorThief.getPalette(imgElement, 5)
    if (pal && pal.length >= 2) {
      const c1 = pal[0]
      const bright = `rgb(${Math.min(255, c1[0] + 60)}, ${Math.min(255, c1[1] + 60)}, ${Math.min(255, c1[2] + 60)})`
      _cache[eraName] = {
        bg: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.2)`,
        text: bright,
        border: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.3)`,
      }
    }
  } catch (e) {
    // ColorThief can fail on certain images — ignore
  }
}
