/**
 * Shared UI utilities for LeakSheet web components.
 */

/**
 * Map quality string to badge variant name.
 * @param {string|null} q - Quality string like "CD Quality", "OG File", etc.
 * @returns {string} Badge variant name (matches badge/index.ts variants)
 */
export function qualityVariant(q: string | null | undefined): string {
  if (!q) return 'na'
  const l = q.toLowerCase()
  if (l.includes('lossless')) return 'hq'
  if (l.includes('og')) return 'og'
  if (l.includes('cd')) return 'cd'
  if (l.includes('high')) return 'hq'
  if (l.includes('low')) return 'lq'
  if (l.includes('recording')) return 'rec'
  return 'na'
}

/**
 * Map available_length to badge variant name.
 * @param {string|null} avail - Available length like "Full", "Partial", "Snippet", etc.
 * @returns {string} Badge variant name
 */
export function availabilityVariant(avail: string | null | undefined): string {
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

export interface EffectiveBadge {
  text: string | null | undefined
  variant: string
  type: 'quality' | 'availability'
}

/**
 * Determine the best badge to display: prefer available_length
 * over quality when quality is "Not Available".
 */
export function effectiveBadge(quality: string | null | undefined, availableLength: string | null | undefined): EffectiveBadge | null {
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

// Gate set for getAvailBadge — determines which availability values add meaningful
// info beyond what the quality badge conveys. Not a canonical enum; availabilityVariant()
// is the source of truth for classification logic.
const _AVAILABILITY_VALUES = new Set([
  'og file', 'og files', 'full', 'tagged', 'stem', 'stem bounce', 'stem bounces',
  'partial', 'snippet', 'confirmed', 'unavailable',
])

export interface AvailBadge {
  text: string | null | undefined
  variant: string
}

/**
 * Determine the secondary availability badge to show alongside the quality badge.
 * Returns { text, variant } when the available_length value adds information
 * beyond what the quality badge already conveys, otherwise returns null.
 */
export function getAvailBadge(quality: string | null | undefined, availableLength: string | null | undefined): AvailBadge | null {
  const avail = availableLength
  if (!avail) return null
  const al = avail.toLowerCase().trim()
  if (al === 'n/a' || al === 'not available') return null
  const q = (quality || '').toLowerCase().trim()
  if (q && q !== 'not available' && q !== 'n/a') {
    // Skip duplicate when quality and availability convey the same thing
    if (al === q) return null
    // Quality badge is already shown — show availability only if it adds info
    if (_AVAILABILITY_VALUES.has(al)) {
      return { text: avail, variant: availabilityVariant(avail) }
    }
  }
  return null
}

/** Badge keys that qualify a version as "best of" content. */
export const BEST_OF_BADGES = new Set(['best', 'special'])

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

/**
 * Compute a CSS style object for a badge with a custom background color.
 * Returns null if color is falsy.
 */
export function coloredBadgeStyle(hexColor: string | null | undefined): Record<string, string> | null {
  if (!hexColor) return null
  const clean = hexColor.replace('#', '')
  if (clean.length !== 6) return null
  return {
    backgroundColor: `${hexColor}40`, // 25% alpha overlay
    color: hexColor,
    borderColor: 'transparent',
  }
}
