<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import EraCard from './EraCard.vue'
import SongList from './SongList.vue'
import VersionRow from './VersionRow.vue'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { getEraColors } from '../composables/useEraColors'

const props = defineProps({
  artist: Object,
})

const emit = defineEmits(['back'])

const expandedEra = ref(null)
const bestOf = ref(false)
const recents = ref(false)
const searchQuery = ref('')
const debouncedQuery = ref('')
let _debounceTimer = null

watch(searchQuery, (val) => {
  clearTimeout(_debounceTimer)
  if (!val.trim()) {
    // Clear instantly for better UX
    debouncedQuery.value = ''
    return
  }
  _debounceTimer = setTimeout(() => {
    debouncedQuery.value = val
  }, 200)
})

onUnmounted(() => {
  clearTimeout(_debounceTimer)
})

const eras = computed(() => props.artist?.eras || [])

const _BEST_OF_BADGES = new Set(['best', 'special'])

function isBestOfSong(song) {
  return _BEST_OF_BADGES.has(song.badge)
}

/** Filter eras/songs based on search query and best-of mode */
const filteredEras = computed(() => {
  let result = eras.value

  // Best-of: only eras that have starred songs
  if (bestOf.value) {
    result = result.filter(era => eraSongs(era).some(isBestOfSong))
  }

  const q = debouncedQuery.value.trim().toLowerCase()
  if (!q) return result

  return result.filter(era => {
    // Match era name or alt names
    if (era.name.toLowerCase().includes(q)) return true
    if (era.alt_names?.some(alt => alt.toLowerCase().includes(q))) return true
    // Match any song in the era
    return eraSongs(era).some(song => songMatchesQuery(song, q))
  })
})

function songMatchesQuery(song, query) {
  if (song.base_name.toLowerCase().includes(query)) return true
  return song.versions?.some(v => {
    if ((v.name || '').toLowerCase().includes(query)) return true
    if (v.alt_titles?.some(alt => alt.toLowerCase().includes(query))) return true
    return false
  }) ?? false
}

/** Filter songs within an era when searching or in best-of mode */
function filteredSongs(era) {
  let songs = eraSongs(era)

  // Best-of: only starred songs
  if (bestOf.value) {
    songs = songs.filter(isBestOfSong)
  }

  const q = debouncedQuery.value.trim().toLowerCase()
  if (!q) return songs
  // If era name or alt name matches, show all (filtered) songs
  if (era.name.toLowerCase().includes(q)) return songs
  if (era.alt_names?.some(alt => alt.toLowerCase().includes(q))) return songs
  return songs.filter(song => songMatchesQuery(song, q))
}

/** Return sections for an era, preserving section structure for dividers */
function eraSections(era) {
  if (!era.sections?.length) return []
  const q = debouncedQuery.value.trim().toLowerCase()
  const filtering = bestOf.value || q

  if (!filtering) return era.sections

  // When filtering, still preserve section structure but filter songs within
  return era.sections
    .map(sec => {
      let songs = sec.songs || []
      if (bestOf.value) songs = songs.filter(isBestOfSong)
      if (q) {
        const eraNameMatch = era.name.toLowerCase().includes(q) ||
          era.alt_names?.some(alt => alt.toLowerCase().includes(q))
        if (!eraNameMatch) songs = songs.filter(song => songMatchesQuery(song, q))
      }
      return { ...sec, songs }
    })
    .filter(sec => sec.songs.length > 0)
}

const isSearching = computed(() => debouncedQuery.value.trim().length > 0)

/** Flat list of individual version results for search mode (Issues 6+7) */
const flatSearchResults = computed(() => {
  const q = debouncedQuery.value.trim().toLowerCase()
  if (!q) return []

  const results = []
  for (const era of eras.value) {
    const songs = eraSongs(era)
    for (const song of songs) {
      // Apply best-of filter if active
      if (bestOf.value && !isBestOfSong(song)) continue
      if (songMatchesQuery(song, q)) {
        for (const version of (song.versions || [])) {
          results.push({ song, version, era })
        }
      }
    }
  }
  return results
})

function eraColorStyle(era) {
  const colors = getEraColors(era.name)
  if (colors) {
    return {
      background: colors.bg,
      color: colors.text,
      borderColor: colors.border,
    }
  }
  return {
    background: 'rgba(78,205,196,0.15)',
    color: 'var(--accent-color)',
    borderColor: 'rgba(78,205,196,0.3)',
  }
}

function toggleEra(eraName) {
  if (bestOf.value) return // All eras stay open in best-of mode
  expandedEra.value = expandedEra.value === eraName ? null : eraName
}

function isEraExpanded(eraName) {
  if (bestOf.value) return true
  return expandedEra.value === eraName
}

function toggleBestOf() {
  bestOf.value = !bestOf.value
  if (!bestOf.value && !recents.value) {
    expandedEra.value = null
  }
}

function toggleRecents() {
  recents.value = !recents.value
  if (!recents.value && !bestOf.value) {
    expandedEra.value = null
  }
}

/** Get songs for an era — data is already fully loaded client-side. */
function eraSongs(era) {
  if (era.songs) return era.songs
  if (era.sections) {
    return era.sections.flatMap(s => s.songs || [])
  }
  return []
}

/** Parse a date string like "12/25/2024", "2024", "December 2024" into a sortable timestamp. */
function _parseLeakDate(dateStr) {
  if (!dateStr) return 0
  // Try Date.parse first — handles "Jan 2, 2026", "February 10, 2026", etc.
  const parsed = Date.parse(dateStr)
  if (!isNaN(parsed)) return parsed
  // Try MM/DD/YYYY or M/D/YYYY
  const slashMatch = dateStr.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/)
  if (slashMatch) {
    return new Date(+slashMatch[3], +slashMatch[1] - 1, +slashMatch[2]).getTime()
  }
  // Try just year
  const yearMatch = dateStr.match(/(\d{4})/)
  if (yearMatch) {
    return new Date(+yearMatch[1], 0, 1).getTime()
  }
  return 0
}

/** Flat list of recently added versions, sorted by leak_date descending. */
const recentResults = computed(() => {
  if (!recents.value) return []

  const q = debouncedQuery.value.trim().toLowerCase()
  const results = []
  for (const era of eras.value) {
    const songs = eraSongs(era)
    for (const song of songs) {
      // Apply best-of filter if active
      if (bestOf.value && !isBestOfSong(song)) continue
      // Apply search filter if active
      if (q && !songMatchesQuery(song, q)) continue
      for (const version of (song.versions || [])) {
        const leakDate = version.leak_date || version.file_date
        if (leakDate) {
          results.push({ song, version, era, _ts: _parseLeakDate(leakDate) })
        }
      }
    }
  }

  // Sort by date descending (most recent first), limit to 50
  results.sort((a, b) => b._ts - a._ts)
  return results.slice(0, 50)
})

</script>

<template>
  <div class="artist-view">
    <div class="artist-header">
      <button class="back-btn" @click="emit('back')" aria-label="Back to home">
        <svg viewBox="0 0 16 16" width="16" height="16">
          <path fill="currentColor" d="M7.78 12.53a.75.75 0 0 1-1.06 0L2.47 8.28a.75.75 0 0 1 0-1.06l4.25-4.25a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L4.81 7h7.44a.75.75 0 0 1 0 1.5H4.81l2.97 2.97a.75.75 0 0 1 0 1.06z"/>
        </svg>
      </button>
      <div class="artist-header-text">
        <h2 class="artist-name">{{ artist.name }}</h2>
        <div class="artist-meta">
          {{ artist.eras?.length || 0 }} eras
        </div>
      </div>
    </div>

    <!-- Search bar + Best Of toggle -->
    <div class="search-bar-wrap">
      <div class="search-bar">
        <svg class="search-icon" viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M11.5 7a4.499 4.499 0 1 1-8.998 0A4.499 4.499 0 0 1 11.5 7zm-.82 4.74a6 6 0 1 1 1.06-1.06l3.04 3.04a.75.75 0 1 1-1.06 1.06l-3.04-3.04z"/>
        </svg>
        <Input
          v-model="searchQuery"
          type="text"
          variant="ghost"
          class="search-input"
          placeholder="Search songs by title..."
          aria-label="Search songs"
        />
        <Button v-if="searchQuery" variant="ghost" size="icon" class="search-clear h-6 w-6 p-0" @click="searchQuery = ''" aria-label="Clear search">
          <svg viewBox="0 0 16 16" width="12" height="12">
            <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
          </svg>
        </Button>
        <Button variant="ghost" size="icon" class="best-of-toggle" :class="{ active: bestOf }" @click="toggleBestOf" aria-label="Toggle best of filter" :aria-pressed="bestOf">
          <span class="best-of-star">&#11088;</span>
        </Button>
        <Button variant="ghost" size="icon" class="best-of-toggle" :class="{ active: recents }" @click="toggleRecents" aria-label="Toggle recently added filter" :aria-pressed="recents">
          <svg viewBox="0 0 16 16" width="16" height="16" style="opacity: inherit">
            <path fill="currentColor" d="M1.5 8a6.5 6.5 0 1 1 13 0 6.5 6.5 0 0 1-13 0zM8 0a8 8 0 1 0 0 16A8 8 0 0 0 8 0zm.5 4.75a.75.75 0 0 0-1.5 0v3.5a.75.75 0 0 0 .37.65l2.5 1.5a.75.75 0 1 0 .76-1.3L8.5 7.87V4.75z"/>
          </svg>
        </Button>
      </div>
    </div>

    <!-- Recents view: flat list sorted by leak date -->
    <!-- Recents view: flat list sorted by leak date (optionally filtered by search + best-of) -->
    <template v-if="recents">
      <div v-if="recentResults.length === 0" class="no-results">
        <template v-if="isSearching">No recent entries matching "{{ searchQuery }}"</template>
        <template v-else>No entries with leak dates found</template>
      </div>
      <div v-else class="search-results">
        <div
          v-for="(result, idx) in recentResults"
          :key="'r' + idx"
          class="search-result-row"
        >
          <div class="search-result-meta">
            <span class="era-badge-pill" :style="eraColorStyle(result.era)">{{ result.era.name }}</span>
            <span v-if="result.version.leak_date" class="leak-date-badge">{{ result.version.leak_date }}</span>
          </div>
          <div class="search-result-version">
            <VersionRow
              :version="result.version"
              :artist-name="artist.name"
              :era-name="result.era.name"
              :era-art="result.era.art_url"
              :hide-alt-titles="true"
            />
          </div>
        </div>
      </div>
    </template>

    <!-- Search results: flat version list (optionally filtered by best-of) -->
    <template v-else-if="isSearching">
      <div v-if="flatSearchResults.length === 0" class="no-results">
        No results for "{{ searchQuery }}"
      </div>
      <div v-else class="search-results">
        <div
          v-for="(result, idx) in flatSearchResults"
          :key="idx"
          class="search-result-row"
        >
          <span class="era-badge-pill" :style="eraColorStyle(result.era)">{{ result.era.name }}</span>
          <div class="search-result-version">
            <VersionRow
              :version="result.version"
              :artist-name="artist.name"
              :era-name="result.era.name"
              :era-art="result.era.art_url"
              :hide-alt-titles="true"
            />
          </div>
        </div>
      </div>
    </template>

    <!-- Normal era browsing -->
    <div v-else class="eras-list" role="list" aria-label="Eras">
      <div v-for="(era, eraIdx) in filteredEras" :key="era.name" class="era-block">
        <EraCard
          :era="era"
          :expanded="isEraExpanded(era.name)"
          :index="eraIdx"
          :sticky="isEraExpanded(era.name)"
          @click="toggleEra(era.name)"
        />

        <!-- Expanded songs panel -->
        <Transition name="slide">
          <div v-if="isEraExpanded(era.name)" class="era-songs-panel">
            <SongList
              :sections="eraSections(era)"
              :songs="filteredSongs(era)"
              :artist-name="artist.name"
              :era-name="era.name"
              :era-art="era.art_url"
            />
          </div>
        </Transition>
      </div>
    </div>
  </div>
</template>

<style scoped>
.artist-view {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px 20px;
}

.artist-header {
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.back-btn {
  color: var(--text-secondary);
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: color 0.15s, background 0.15s;
}

.back-btn:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.08);
}

.artist-header-text {
  min-width: 0;
}

.artist-name {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.5px;
}

.artist-meta {
  color: var(--text-secondary);
  font-size: 13px;
  margin-top: 4px;
}

/* Search */
.search-bar-wrap {
  margin-bottom: 20px;
}

.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 14px;
  transition: border-color 0.15s;
}

.search-bar:focus-within {
  border-color: rgba(255, 255, 255, 0.2);
}

.search-icon {
  color: var(--text-dim);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  font-size: 14px;
  color: var(--text-primary);
}

.search-input::placeholder {
  color: var(--text-dim);
}

.search-clear {
  color: var(--text-dim);
  flex-shrink: 0;
  min-width: 44px;
  min-height: 44px;
  -webkit-tap-highlight-color: transparent;
}

.search-clear:hover {
  color: var(--text-primary);
}

.best-of-toggle {
  flex-shrink: 0;
  opacity: 0.5;
  border: 1px solid transparent;
  min-width: 44px;
  min-height: 44px;
  -webkit-tap-highlight-color: transparent;
}

.best-of-toggle:hover {
  opacity: 0.8;
}

.best-of-toggle.active {
  opacity: 1;
  background: rgba(255, 215, 0, 0.12);
  border-color: rgba(255, 215, 0, 0.3);
}

.best-of-star {
  font-size: 16px;
  line-height: 1;
}

.no-results {
  text-align: center;
  color: var(--text-secondary);
  font-size: 14px;
  padding: 40px 0;
}

.eras-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.era-songs-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-top: 2px solid var(--accent-color);
  border-radius: 0 0 12px 12px;
  padding: 0 16px 16px;
}

/* Transition */
.slide-enter-active,
.slide-leave-active {
  transition: opacity 0.25s ease;
}
.slide-enter-from,
.slide-leave-to {
  opacity: 0;
}
.slide-enter-to,
.slide-leave-from {
  opacity: 1;
}

/* Search results (flat list) */
.search-results {
  display: flex;
  flex-direction: column;
}

.search-result-row {
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  padding: 8px 0 0;
}

.search-result-row:last-child {
  border-bottom: none;
}

.era-badge-pill {
  display: inline-block;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid;
  white-space: nowrap;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-left: 8px;
}

.search-result-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.leak-date-badge {
  font-size: 10px;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.search-result-version {
  margin-top: 0;
}

@media (max-width: 640px) {
  .artist-view { padding: 16px 12px; }
  .artist-name { font-size: 22px; }
  .era-badge-pill { max-width: 140px; font-size: 8px; padding: 2px 6px; }
}
</style>
