<script setup lang="ts">
import { computed, watch, nextTick, ref } from 'vue'
import EraCard from './EraCard.vue'
import SongList from './SongList.vue'
import VersionRow from './VersionRow.vue'
import ContextMenu from './ContextMenu.vue'
import SongDescriptionModal from './SongDescriptionModal.vue'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { getEraColors } from '../composables/useEraColors'
import { playerState, setEraSongs, findStreamableLink } from '../composables/usePlayer'
import { useEraFiltering, eraSongs } from '../composables/useEraFiltering'
import { provideSharedOverlays } from '../composables/useSharedOverlays'
import type { Artist } from '../composables/useEraFiltering'

const props = defineProps<{
  artist: Artist
}>()

const emit = defineEmits<{
  back: []
}>()

const eras = computed(() => props.artist?.eras || [])

const {
  contextMenuState,
  closeContextMenu,
  descriptionState,
  closeDescription,
} = provideSharedOverlays()

const {
  searchQuery,
  bestOf,
  recents,
  isSearching,
  filteredEras,
  flatSearchResults,
  recentResults,
  filteredSongs,
  filteredSections: eraSections,
  toggleEra,
  isEraExpanded,
  toggleBestOf,
  toggleRecents,
} = useEraFiltering(eras)

const eraBlockRefs = ref<Record<string, HTMLElement | null>>({})

function setEraBlockRef(name: string) {
  return (el: any) => { eraBlockRefs.value[name] = el }
}

function handleToggleEra(eraName: string) {
  const wasExpanded = isEraExpanded(eraName)
  toggleEra(eraName)
  if (!wasExpanded) {
    // Opening a new era — scroll it into view after DOM settles.
    // Use a short delay so the old era's collapse doesn't shift the target.
    nextTick(() => {
      requestAnimationFrame(() => {
        const el = eraBlockRefs.value[eraName]
        if (el) {
          el.scrollIntoView({ behavior: 'instant', block: 'start' })
        }
      })
    })
  }
}

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

/**
 * Auto-advance watcher: when a track starts playing, populate era context
 * so the next song in the era plays automatically when it finishes.
 * Respects best-of filter — only advances to best/special songs if enabled.
 */
watch(() => playerState.track, (track) => {
  if (!track) return
  const eraName = playerState.eraName
  if (!eraName) return

  // Find the era that matches the currently playing track
  const era = eras.value.find(e => e.name === eraName)
  if (!era) return

  // Build flat list of first-streamable version per song (play order)
  const songs = eraSongs(era)
  const versions = []
  for (const song of songs) {
    if (!song.versions?.length) continue
    const streamable = song.versions.find(v => findStreamableLink(v.links))
    if (streamable) {
      versions.push(streamable)
    }
  }

  if (versions.length > 0) {
    setEraSongs(
      versions,
      props.artist?.name || playerState.artistName,
      eraName,
      playerState.artUrl,
      bestOf.value,
    )
  }
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
          :key="`r:${result.era.name}:${result.version.name}:${idx}`"
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
          :key="`s:${result.era.name}:${result.version.name}:${idx}`"
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
      <div v-for="(era, eraIdx) in filteredEras" :key="era.name" class="era-block" :ref="setEraBlockRef(era.name)">
        <EraCard
          :era="era"
          :expanded="isEraExpanded(era.name)"
          :index="eraIdx"
          :sticky="isEraExpanded(era.name)"
          @click="handleToggleEra(era.name)"
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

    <!-- Shared context menu (single instance for all rows) -->
    <ContextMenu
      v-if="contextMenuState"
      :x="contextMenuState.x"
      :y="contextMenuState.y"
      :song="contextMenuState.song"
      :version="contextMenuState.version"
      :artist-name="contextMenuState.artistName"
      :era-name="contextMenuState.eraName"
      :era-art="contextMenuState.eraArt"
      @close="closeContextMenu"
      @show-description="() => {
        if (contextMenuState) {
          descriptionState = {
            song: contextMenuState.song,
            version: contextMenuState.version,
            artistName: contextMenuState.artistName,
            eraName: contextMenuState.eraName,
            eraArt: contextMenuState.eraArt,
          }
        }
        closeContextMenu()
      }"
    />

    <!-- Shared description modal (single instance for all rows) -->
    <SongDescriptionModal
      v-if="descriptionState"
      :song="descriptionState.song"
      :version="descriptionState.version"
      :era-art="descriptionState.eraArt"
      :era-name="descriptionState.eraName"
      :artist-name="descriptionState.artistName"
      @close="closeDescription"
    />
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
