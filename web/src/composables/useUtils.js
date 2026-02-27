/**
 * Shared UI utilities for LeakSheet web components.
 */

/**
 * Map quality string to CSS class for badge styling.
 * @param {string|null} q - Quality string like "CD Quality", "OG File", etc.
 * @returns {string} CSS class name
 */
export function qualityClass(q) {
  if (!q) return 'q-na'
  const l = q.toLowerCase()
  if (l.includes('og') || l.includes('lossless')) return 'q-og'
  if (l.includes('cd')) return 'q-cd'
  if (l.includes('high')) return 'q-hq'
  if (l.includes('low')) return 'q-lq'
  if (l.includes('recording')) return 'q-rec'
  return 'q-na'
}

/**
 * Map available_length to CSS class for availability badge styling.
 * @param {string|null} avail - Available length like "Full", "Partial", "Snippet", etc.
 * @returns {string} CSS class name
 */
export function availabilityClass(avail) {
  if (!avail) return 'a-na'
  const l = avail.toLowerCase()
  if (l === 'full') return 'a-full'
  if (l.includes('partial') || l.includes('cut')) return 'a-partial'
  if (l.includes('snippet')) return 'a-snippet'
  if (l.includes('confirmed')) return 'a-confirmed'
  if (l.includes('unavailable')) return 'a-unavailable'
  return 'a-na'
}

/**
 * Determine the best badge to display: prefer available_length
 * over quality when quality is "Not Available".
 * @param {string|null} quality
 * @param {string|null} availableLength
 * @returns {{ text: string, cssClass: string, type: 'quality'|'availability' }|null}
 */
export function effectiveBadge(quality, availableLength) {
  const qLower = (quality || '').toLowerCase().trim()
  const aLower = (availableLength || '').toLowerCase().trim()

  // If quality is "not available" or empty, show availability status instead
  if (!qLower || qLower === 'not available' || qLower === 'n/a') {
    if (aLower && aLower !== 'n/a') {
      return { text: availableLength, cssClass: availabilityClass(availableLength), type: 'availability' }
    }
    // Both empty/NA — don't show a badge
    return null
  }

  // Quality is meaningful — show it
  return { text: quality, cssClass: qualityClass(quality), type: 'quality' }
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
