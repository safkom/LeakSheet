/**
 * Shared UI utilities for LeakSheet web components.
 */

/**
 * Map quality string to badge variant name.
 * @param {string|null} q - Quality string like "CD Quality", "OG File", etc.
 * @returns {string} Badge variant name (matches badge/index.ts variants)
 */
export function qualityVariant(q) {
  if (!q) return 'na'
  const l = q.toLowerCase()
  if (l.includes('og') || l.includes('lossless')) return 'og'
  if (l.includes('cd')) return 'cd'
  if (l.includes('high')) return 'hq'
  if (l.includes('low')) return 'lq'
  if (l.includes('recording')) return 'rec'
  return 'na'
}

/** @deprecated Use qualityVariant instead */
export function qualityClass(q) {
  return 'q-' + qualityVariant(q)
}

/**
 * Map available_length to badge variant name.
 * @param {string|null} avail - Available length like "Full", "Partial", "Snippet", etc.
 * @returns {string} Badge variant name
 */
export function availabilityVariant(avail) {
  if (!avail) return 'na'
  const l = avail.toLowerCase()
  if (l.includes('og file') || l.includes('og files')) return 'ogfile'
  if (l === 'full') return 'full'
  if (l.includes('tagged')) return 'tagged'
  if (l.includes('stem')) return 'stem'
  if (l.includes('partial') || l.includes('cut')) return 'partial'
  if (l.includes('snippet')) return 'snippet'
  if (l.includes('confirmed')) return 'confirmed'
  if (l.includes('unavailable')) return 'unavailable'
  return 'na'
}

/** @deprecated Use availabilityVariant instead */
export function availabilityClass(avail) {
  const v = availabilityVariant(avail)
  return v === 'na' ? 'a-na' : `a-${v}`
}

/**
 * Determine the best badge to display: prefer available_length
 * over quality when quality is "Not Available".
 * @param {string|null} quality
 * @param {string|null} availableLength
 * @returns {{ text: string, variant: string, type: 'quality'|'availability' }|null}
 */
export function effectiveBadge(quality, availableLength) {
  const qLower = (quality || '').toLowerCase().trim()
  const aLower = (availableLength || '').toLowerCase().trim()

  // If quality is "not available" or empty, show availability status instead
  if (!qLower || qLower === 'not available' || qLower === 'n/a') {
    if (aLower && aLower !== 'n/a') {
      return { text: availableLength, variant: availabilityVariant(availableLength), type: 'availability' }
    }
    // Both empty/NA — don't show a badge
    return null
  }

  // Skip duplicate badge when quality and availability convey the same thing
  // (e.g. both say "OG File")
  if (qLower === aLower) {
    return { text: quality, variant: qualityVariant(quality), type: 'quality' }
  }

  // Quality is meaningful — show it
  return { text: quality, variant: qualityVariant(quality), type: 'quality' }
}

/**
 * Determine the secondary availability badge to show alongside the quality badge.
 * Returns { text, variant } when the available_length value adds information
 * beyond what the quality badge already conveys, otherwise returns null.
 * @param {string|null} quality
 * @param {string|null} availableLength
 * @returns {{ text: string, variant: string }|null}
 */
export function getAvailBadge(quality, availableLength) {
  const avail = availableLength
  if (!avail) return null
  const al = avail.toLowerCase().trim()
  if (al === 'n/a' || al === 'not available') return null
  const q = (quality || '').toLowerCase().trim()
  if (q && q !== 'not available' && q !== 'n/a') {
    // Skip duplicate when quality and availability convey the same thing
    if (al === q) return null
    // Quality badge is already shown — show availability only if it adds info
    if (['og file', 'og files', 'full', 'tagged', 'stem', 'stem bounce', 'stem bounces', 'partial', 'snippet', 'confirmed', 'unavailable'].includes(al)) {
      return { text: avail, variant: availabilityVariant(avail) }
    }
  }
  return null
}

/**
 * Badge emoji map (same as parser Badge enum).
 */
export const BADGE_MAP = {
  best: '⭐',
  special: '✨',
  worst: '🗑️',
  grail: '🏆',
  wanted: '🏅',
  ai: '🤖',
}
