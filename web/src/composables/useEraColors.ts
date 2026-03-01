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
