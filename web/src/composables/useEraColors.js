/**
 * Shared reactive era color cache.
 * Populated by EraCard after ColorThief extraction, consumed by ArtistView for search badges.
 */
import { reactive } from 'vue'

const _cache = reactive(new Map())

export function setEraColors(eraName, colors) {
  _cache.set(eraName, colors)
}

export function getEraColors(eraName) {
  return _cache.get(eraName) || null
}
