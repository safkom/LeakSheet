/**
 * Metadata fetching and caching composable.
 *
 * Fetches audio file metadata from provider APIs via /api/metadata,
 * caches results per-link, and provides helpers for display.
 */

import { ref, watch, type Ref } from 'vue'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FileMetadata {
  provider: string
  container?: string
  codec?: string
  codec_profile?: string
  bitrate?: string
  sample_rate?: string
  bits_per_sample?: string
  lossless?: boolean
  channels?: number | string
  duration?: string
  quality_mismatch?: boolean
  estimated_bitrate?: number
  frequency_cutoff?: number
  file_size?: number
  mime_type?: string
  filename?: string
  artist?: string
  title?: string
}

// ---------------------------------------------------------------------------
// Module-level cache
// ---------------------------------------------------------------------------

const _cache = new Map<string, FileMetadata | null>()
const _pending = new Map<string, Promise<FileMetadata | null>>()

// ---------------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------------

async function _fetchImpl(link: string): Promise<FileMetadata | null> {
  try {
    const res = await fetch(`/api/metadata?url=${encodeURIComponent(link)}`, {
      signal: AbortSignal.timeout(15000),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

/** Fetch metadata for a file-sharing link. Results are cached per-link. */
export async function fetchMetadata(link: string): Promise<FileMetadata | null> {
  if (_cache.has(link)) return _cache.get(link)!
  if (_pending.has(link)) return _pending.get(link)!

  const promise = _fetchImpl(link)
  _pending.set(link, promise)
  try {
    const result = await promise
    _cache.set(link, result)
    return result
  } finally {
    _pending.delete(link)
  }
}

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

/** Human-readable format summary, e.g. "MP3 · 320kbps" or "WAV · Lossless" */
export function formatMetadataSummary(m: FileMetadata): string {
  const parts: string[] = []
  if (m.codec && m.codec !== m.container) parts.push(m.codec)
  else if (m.container) parts.push(m.container)
  if (m.lossless === true) parts.push('Lossless')
  else if (m.bitrate) parts.push(m.bitrate)
  else if (m.estimated_bitrate) parts.push(`~${m.estimated_bitrate}kbps`)
  return parts.join(' \u00B7 ')
}

/** Map a metadata field to an existing badge variant. */
export function metadataBadgeVariant(field: string, value: unknown): string {
  if (field === 'lossless') return value === true ? 'lossless' : 'hq'
  if (field === 'quality_mismatch') return value === true ? 'lq' : 'full'
  if (field === 'bitrate' || field === 'estimated_bitrate') {
    const num = parseInt(String(value))
    if (!isNaN(num)) {
      if (num >= 1000) return 'lossless'
      if (num >= 320) return 'hq'
      if (num >= 192) return 'cd'
      return 'lq'
    }
  }
  return 'secondary'
}

/** Estimate file size from bitrate and duration in seconds. Returns e.g. "~12 MB". */
export function estimateFileSize(m: FileMetadata, durationSecs: number): string | null {
  if (!durationSecs || durationSecs <= 0) return null
  let kbps = 0
  if (m.estimated_bitrate) kbps = m.estimated_bitrate
  else if (m.bitrate) {
    const parsed = parseFloat(m.bitrate)
    if (!isNaN(parsed)) kbps = parsed
  }
  if (kbps <= 0) return null
  const bytes = (kbps * 1000 / 8) * durationSecs
  if (bytes >= 1024 * 1024 * 1024) return `~${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
  if (bytes >= 1024 * 1024) return `~${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `~${(bytes / 1024).toFixed(0)} KB`
}

/** Check if the file is "large" (lossless or high bitrate). */
export function isLargeFile(m: FileMetadata): boolean {
  if (m.lossless === true) return true
  const br = m.estimated_bitrate || parseInt(m.bitrate || '0')
  return br >= 1000
}

// ---------------------------------------------------------------------------
// Reactive composable
// ---------------------------------------------------------------------------

/** Reactive wrapper — watches a link ref and fetches metadata. */
export function useMetadata(linkRef: Ref<string | null>) {
  const metadata = ref<FileMetadata | null>(null)
  const loading = ref(false)

  watch(linkRef, async (link) => {
    if (!link) { metadata.value = null; return }
    loading.value = true
    metadata.value = await fetchMetadata(link)
    loading.value = false
  }, { immediate: true })

  return { metadata, loading }
}
