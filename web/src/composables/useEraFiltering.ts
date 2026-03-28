/**
 * Era/song filtering composable.
 *
 * Extracted from ArtistView to keep components thin.
 * Handles search, best-of filtering, recents, and debounced queries.
 */
import { ref, computed, watch, onUnmounted, type Ref, type ComputedRef } from 'vue'
import { BEST_OF_BADGES } from './useUtils'

// ---------------------------------------------------------------------------
// Types (mirrors backend Pydantic models)
// ---------------------------------------------------------------------------

export interface SongVersion {
  name: string
  version_tag?: string | null
  badge?: string | null
  featuring?: string | null
  producers?: string | null
  collaboration?: string | null
  refs?: string | null
  alt_titles?: string[]
  notes?: string | null
  og_filename?: string | null
  samples?: string[]
  track_length?: string | null
  file_date?: string | null
  leak_date?: string | null
  available_length?: string | null
  quality?: string | null
  links?: string[]
  date_of_recording?: string | null
  type?: string | null
}

export interface Song {
  base_name: string
  versions: SongVersion[]
  badge?: string | null
  available_length?: string | null
  quality?: string | null
  track_length?: string | null
  leak_date?: string | null
  file_date?: string | null
}

export interface Section {
  name: string
  group?: string | null
  songs: Song[]
}

export interface Era {
  name: string
  alt_names?: string[]
  description?: string | null
  timeline?: { date: string; event: string }[]
  stats_raw?: string | null
  stats?: Record<string, number> | null
  art_url?: string | null
  highlighted_producers?: string[]
  sections?: Section[]
  song_count?: number
  version_count?: number
}

export interface Artist {
  name: string
  slug: string
  source_url?: string | null
  eras: Era[]
  total_songs?: number
  total_versions?: number
}

// ---------------------------------------------------------------------------
// Pure helpers (no reactivity)
// ---------------------------------------------------------------------------

export function isBestOfSong(song: Song): boolean {
  return BEST_OF_BADGES.has(song.badge ?? '')
}

/**
 * Pre-built search index — lowercased searchable strings per song.
 * Built once per artist load, avoids repeated .toLowerCase() on every keystroke.
 */
const _searchIndex = new WeakMap<Song, string>()

/** Pre-lowercased scoring fields — avoids repeated .toLowerCase() in scoreSong. */
const _scoreIndex = new WeakMap<Song, { bn: string; alts: string[] }>()

function _getSongSearchText(song: Song): string {
  let cached = _searchIndex.get(song)
  if (cached !== undefined) return cached
  const parts = [song.base_name.toLowerCase()]
  for (const v of (song.versions || [])) {
    if (v.name) parts.push(v.name.toLowerCase())
    if (v.alt_titles) {
      for (const alt of v.alt_titles) {
        parts.push(alt.toLowerCase())
      }
    }
  }
  cached = parts.join('\0')
  _searchIndex.set(song, cached)
  return cached
}

export function songMatchesQuery(song: Song, query: string): boolean {
  return _getSongSearchText(song).includes(query)
}

/**
 * Score a song against a query for ranked search results.
 * Higher score = better match. Returns 0 if no match.
 *
 * Scoring tiers:
 *   100 — exact base_name match
 *    90 — exact alt_title match
 *    70 — base_name starts with query
 *    60 — alt_title starts with query
 *    40 — base_name contains query
 *    20 — version name or alt_title contains query (deep match)
 */
export function scoreSong(song: Song, query: string): number {
  let idx = _scoreIndex.get(song)
  if (!idx) {
    const alts: string[] = []
    for (const v of (song.versions || [])) {
      if (v.alt_titles) {
        for (const alt of v.alt_titles) alts.push(alt.toLowerCase())
      }
    }
    idx = { bn: song.base_name.toLowerCase(), alts }
    _scoreIndex.set(song, idx)
  }
  const { bn, alts } = idx

  if (bn === query) return 100
  if (alts.some(a => a === query)) return 90
  if (bn.startsWith(query)) return 70
  if (alts.some(a => a.startsWith(query))) return 60
  if (bn.includes(query)) return 40

  // Deep match in version names
  for (const v of (song.versions || [])) {
    if (v.name?.toLowerCase().includes(query)) return 20
  }
  if (alts.some(a => a.includes(query))) return 20

  return 0
}

/** Get songs for an era from its sections. */
export function eraSongs(era: Era): Song[] {
  if (era.sections) {
    return era.sections.flatMap(s => s.songs || [])
  }
  return []
}

/** Parse a date string like "12/25/2024", "2024", "December 2024" into a sortable timestamp. */
function _parseLeakDate(dateStr: string | null | undefined): number {
  if (!dateStr) return 0
  const parsed = Date.parse(dateStr)
  if (!isNaN(parsed)) return parsed
  const slashMatch = dateStr.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/)
  if (slashMatch) {
    return new Date(+slashMatch[3], +slashMatch[1] - 1, +slashMatch[2]).getTime()
  }
  const yearMatch = dateStr.match(/(\d{4})/)
  if (yearMatch) {
    return new Date(+yearMatch[1], 0, 1).getTime()
  }
  return 0
}

// ---------------------------------------------------------------------------
// Composable
// ---------------------------------------------------------------------------

export interface SearchResult {
  song: Song
  version: SongVersion
  era: Era
}

export interface RecentResult extends SearchResult {
  _ts: number
}

export function useEraFiltering(eras: ComputedRef<Era[]>) {
  const searchQuery = ref('')
  const debouncedQuery = ref('')
  const bestOf = ref(false)
  const recents = ref(false)
  const noSnippets = ref(false)
  const expandedEra: Ref<string | null> = ref(null)

  // Debounce search input
  let _debounceTimer: ReturnType<typeof setTimeout> | null = null

  watch(searchQuery, (val) => {
    if (_debounceTimer) clearTimeout(_debounceTimer)
    if (!val.trim()) {
      debouncedQuery.value = ''
      return
    }
    _debounceTimer = setTimeout(() => {
      debouncedQuery.value = val
    }, 200)
  })

  onUnmounted(() => {
    if (_debounceTimer) clearTimeout(_debounceTimer)
  })

  const isSearching = computed(() => debouncedQuery.value.trim().length > 0)

  /** Filter a song list to only songs that have at least one best-of version,
   *  narrowing each song's versions to just the best-of ones. */
  function _filterToBestOf(songs: Song[]): Song[] {
    return songs
      .map(song => {
        const bestVersions = (song.versions || []).filter(v => BEST_OF_BADGES.has(v.badge ?? ''))
        return bestVersions.length ? { ...song, versions: bestVersions } : null
      })
      .filter((s): s is Song => s !== null)
  }

  function _isSnippet(v: SongVersion): boolean {
    return (v.available_length ?? '').toLowerCase().includes('snippet')
  }

  /** Filter a song list to remove snippet-only songs; narrows each song's versions too. */
  function _filterNoSnippets(songs: Song[]): Song[] {
    return songs
      .map(song => {
        const nonSnippet = (song.versions || []).filter(v => !_isSnippet(v))
        return nonSnippet.length ? { ...song, versions: nonSnippet } : null
      })
      .filter((s): s is Song => s !== null)
  }

  // ── Filtered eras ──

  const filteredEras = computed(() => {
    let result = eras.value

    if (bestOf.value) {
      result = result.filter(era => eraSongs(era).some(isBestOfSong))
    }

    const q = debouncedQuery.value.trim().toLowerCase()
    if (!q) return result

    return result.filter(era => {
      if (era.name.toLowerCase().includes(q)) return true
      if (era.alt_names?.some(alt => alt.toLowerCase().includes(q))) return true
      return eraSongs(era).some(song => songMatchesQuery(song, q))
    })
  })

  // ── Filtered songs within an era (memoized map) ──

  const _filteredSongsMap = computed(() => {
    const map = new Map<string, Song[]>()
    const q = debouncedQuery.value.trim().toLowerCase()
    for (const era of eras.value) {
      let songs = eraSongs(era)
      if (bestOf.value) songs = _filterToBestOf(songs)
      if (noSnippets.value) songs = _filterNoSnippets(songs)
      if (q) {
        const eraNameMatch = era.name.toLowerCase().includes(q) ||
          era.alt_names?.some(alt => alt.toLowerCase().includes(q))
        if (!eraNameMatch) {
          songs = songs.filter(song => songMatchesQuery(song, q))
        }
      }
      map.set(era.name, songs)
    }
    return map
  })

  function filteredSongs(era: Era): Song[] {
    return _filteredSongsMap.value.get(era.name) ?? eraSongs(era)
  }

  // ── Filtered sections (memoized map) ──

  const _filteredSectionsMap = computed(() => {
    const map = new Map<string, Section[]>()
    const q = debouncedQuery.value.trim().toLowerCase()
    const filtering = bestOf.value || q

    for (const era of eras.value) {
      if (!era.sections?.length) {
        map.set(era.name, [])
        continue
      }
      if (!filtering) {
        map.set(era.name, era.sections)
        continue
      }
      const result = era.sections
        .map(sec => {
          let songs = sec.songs || []
          if (bestOf.value) songs = _filterToBestOf(songs)
          if (noSnippets.value) songs = _filterNoSnippets(songs)
          if (q) {
            const eraNameMatch = era.name.toLowerCase().includes(q) ||
              era.alt_names?.some(alt => alt.toLowerCase().includes(q))
            if (!eraNameMatch) songs = songs.filter(song => songMatchesQuery(song, q))
          }
          return { ...sec, songs }
        })
        .filter(sec => sec.songs.length > 0)
      map.set(era.name, result)
    }
    return map
  })

  function filteredSections(era: Era): Section[] {
    return _filteredSectionsMap.value.get(era.name) ?? []
  }

  // ── Flat search results (ranked by match quality) ──

  const flatSearchResults = computed<SearchResult[]>(() => {
    const q = debouncedQuery.value.trim().toLowerCase()
    if (!q) return []

    const scored: Array<{ result: SearchResult; score: number }> = []
    for (const era of eras.value) {
      const songs = eraSongs(era)
      for (const song of songs) {
        const score = scoreSong(song, q)
        if (score > 0) {
          for (const version of (song.versions || [])) {
            if (bestOf.value && !BEST_OF_BADGES.has(version.badge ?? '')) continue
            if (noSnippets.value && _isSnippet(version)) continue
            scored.push({ result: { song, version, era }, score })
          }
        }
      }
    }

    // Sort by score descending (era order preserved within same score tier)
    scored.sort((a, b) => b.score - a.score)
    return scored.map(s => s.result)
  })

  const searchResultCount = computed(() => flatSearchResults.value.length)

  // ── Recents ──

  const recentResults = computed<RecentResult[]>(() => {
    if (!recents.value) return []

    const q = debouncedQuery.value.trim().toLowerCase()
    const results: RecentResult[] = []
    for (const era of eras.value) {
      const songs = eraSongs(era)
      for (const song of songs) {
        if (bestOf.value && !isBestOfSong(song)) continue
        if (q && !songMatchesQuery(song, q)) continue
        for (const version of (song.versions || [])) {
          if (bestOf.value && !BEST_OF_BADGES.has(version.badge ?? '')) continue
          if (noSnippets.value && _isSnippet(version)) continue
          const leakDate = version.leak_date || version.file_date
          if (leakDate) {
            results.push({ song, version, era, _ts: _parseLeakDate(leakDate) })
          }
        }
      }
    }

    results.sort((a, b) => b._ts - a._ts)
    return results
  })

  // ── Era expand/collapse ──

  function toggleEra(eraName: string): boolean {
    if (bestOf.value) return false
    expandedEra.value = expandedEra.value === eraName ? null : eraName
    return true
  }

  function isEraExpanded(eraName: string): boolean {
    if (bestOf.value) return true
    return expandedEra.value === eraName
  }

  function toggleBestOf(): void {
    bestOf.value = !bestOf.value
    if (!bestOf.value && !recents.value) {
      expandedEra.value = null
    }
  }

  function toggleRecents(): void {
    recents.value = !recents.value
    if (!recents.value && !bestOf.value) {
      expandedEra.value = null
    }
  }

  function toggleNoSnippets(): void {
    noSnippets.value = !noSnippets.value
  }

  return {
    // State
    searchQuery,
    debouncedQuery,
    bestOf,
    recents,
    noSnippets,
    expandedEra,
    isSearching,

    // Computed
    filteredEras,
    flatSearchResults,
    searchResultCount,
    recentResults,

    // Methods
    filteredSongs,
    filteredSections,
    toggleEra,
    isEraExpanded,
    toggleBestOf,
    toggleRecents,
    toggleNoSnippets,
  }
}
