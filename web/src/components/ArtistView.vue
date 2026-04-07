<script setup lang="ts">
import { computed, watch, nextTick, ref, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import { toast } from 'vue-sonner'
import EraCard from './EraCard.vue'
import SongList from './SongList.vue'
import SongRow from './SongRow.vue'
import VersionRow from './VersionRow.vue'
import ArtistStatsBar from './ArtistStatsBar.vue'
import NoticeBanner from './NoticeBanner.vue'
import ScrollToTop from './ScrollToTop.vue'
const ContextMenu = defineAsyncComponent(() => import('./ContextMenu.vue'))
const SongDescriptionModal = defineAsyncComponent(() => import('./SongDescriptionModal.vue'))
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { getEraColors } from '../composables/useEraColors'
import { playerState, setEraSongs, findStreamableLink } from '../composables/usePlayer'
import { useEraFiltering, eraSongs } from '../composables/useEraFiltering'
import { provideSharedOverlays, type DescriptionModalState } from '../composables/useSharedOverlays'
import { favouritesForArtist } from '../composables/useFavourites'
import { eraStats } from '../composables/useEraStats'
import { useEraNavigation } from '../composables/useEraNavigation'
import type { Artist } from '../composables/useEraFiltering'

const props = defineProps<{
  artist: Artist
}>()

const emit = defineEmits<{
  back: []
}>()

const noticesDismissed = ref(false)
watch(() => props.artist, () => { noticesDismissed.value = false })

const eras = computed(() => props.artist?.eras || [])

const {
  contextMenuState,
  closeContextMenu,
  descriptionState,
  showDescription,
  closeDescription,
} = provideSharedOverlays()

const {
  searchQuery,
  bestOf,
  recents,
  noSnippets,
  isSearching,
  filteredEras,
  flatSearchResults,
  searchResultCount,
  recentResults,
  filteredSongs,
  filteredSections: eraSections,
  toggleEra,
  isEraExpanded,
  toggleBestOf,
  toggleRecents,
  toggleNoSnippets,
} = useEraFiltering(eras)

// ── Stats ──
const eraStatsMap = computed(() => {
  const map = new Map()
  for (const era of eras.value) {
    map.set(era.name, eraStats(era))
  }
  return map
})

// Derive overall stats from eraStatsMap to avoid calling eraStats() twice per era
const overallStats = computed(() => {
  let total = 0, available = 0, snippets = 0, confirmed = 0, fullHQ = 0
  for (const s of eraStatsMap.value.values()) {
    total += s.total; available += s.available; snippets += s.snippets
    confirmed += s.confirmed; fullHQ += s.fullHQ
  }
  return { total, available, snippets, confirmed, fullHQ }
})

// ── Era navigation ──
const {
  showScrollTop,
  setupObservers,
  scrollToEra,
  scrollToTop,
  cleanup: cleanupNav,
} = useEraNavigation()

// ---------------------------------------------------------------------------
// Favourites
// ---------------------------------------------------------------------------

const showFavourites = ref(false)

const artistFavourites = computed(() => {
  if (!showFavourites.value) return []
  return favouritesForArtist(props.artist.slug)
})

/** Group favourites by era for the favourites view */
const artistFavouritesByEra = computed(() => {
  const map = new Map<string, { eraName: string; eraArt: string | null; entries: typeof artistFavourites.value }>()
  for (const entry of artistFavourites.value) {
    if (!map.has(entry.eraName)) {
      map.set(entry.eraName, { eraName: entry.eraName, eraArt: entry.eraArt, entries: [] })
    }
    map.get(entry.eraName)!.entries.push(entry)
  }
  return [...map.values()]
})

// ---------------------------------------------------------------------------

const eraBlockRefs = ref<Record<string, HTMLElement | null>>({})

function setEraBlockRef(name: string) {
  return (el: any) => { eraBlockRefs.value[name] = el }
}

function handleToggleEra(eraName: string) {
  const wasExpanded = isEraExpanded(eraName)
  const toggled = toggleEra(eraName)
  if (!toggled) {
    toast.info('Turn off Best Of to expand eras individually')
    return
  }
  if (!wasExpanded) {
    // Opening a new era — scroll the era card to the top of the viewport
    // after a brief delay so any collapsing era has time to begin shrinking.
    setTimeout(() => {
      scrollToEra(eraName, eraBlockRefs.value)
    }, 50)
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
 * Auto-advance watcher: when the playing era or best-of filter changes,
 * populate era context so the next song plays automatically.
 * Only rebuilds the song list when the era name or bestOf changes,
 * not on every track change within the same era.
 */
watch(
  () => [playerState.eraName, bestOf.value] as const,
  ([eraName, _bestOf]) => {
    if (!eraName || !playerState.track) return

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
        _bestOf,
      )
    }
  },
)

function handleShowDescription(payload: DescriptionModalState): void {
  showDescription(payload)
  closeContextMenu()
}

// Recents: paginated loading via IntersectionObserver to avoid rendering all entries at once.
const RECENTS_PAGE = 60
const recentsLimit = ref(RECENTS_PAGE)
const recentsSentinel = ref<HTMLElement | null>(null)
let recentsObserver: IntersectionObserver | null = null

const visibleRecentResults = computed(() =>
  recentResults.value.slice(0, recentsLimit.value)
)

function _setupRecentsObserver() {
  recentsObserver?.disconnect()
  if (!recentsSentinel.value) return
  recentsObserver = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) {
      recentsLimit.value += RECENTS_PAGE
    }
  }, { rootMargin: '300px' })
  recentsObserver.observe(recentsSentinel.value)
}

watch(recents, (val) => {
  recentsObserver?.disconnect()
  if (val) {
    recentsLimit.value = RECENTS_PAGE
    nextTick(_setupRecentsObserver)
  }
})

onUnmounted(() => {
  recentsObserver?.disconnect()
  cleanupNav()
})

onMounted(() => {
  // Give Vue a tick to render era blocks before observing
  nextTick(() => {
    if (Object.keys(eraBlockRefs.value).length > 0) {
      setupObservers(eraBlockRefs.value)
    }
  })
})

// Re-setup observers only when the set of visible era names changes
let _lastObservedEraKey = ''
watch(filteredEras, (eras) => {
  const key = eras.map(e => e.name).join('\0')
  if (key === _lastObservedEraKey) return
  _lastObservedEraKey = key
  nextTick(() => setupObservers(eraBlockRefs.value))
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
      </div>
    </div>

    <!-- Tracker notices -->
    <NoticeBanner
      v-if="artist.notices?.length && !noticesDismissed"
      :notices="artist.notices"
      @dismiss="noticesDismissed = true"
    />

    <!-- Artist stats bar -->
    <ArtistStatsBar :stats="overallStats" />

    <!-- Search bar + Best Of toggle -->
    <div class="search-bar-wrap">
      <div class="search-bar" :class="{ 'has-results': isSearching && searchResultCount > 0 }">
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
        <Button variant="ghost" size="icon" class="recents-toggle" :class="{ active: recents }" @click="toggleRecents" aria-label="Toggle recently added filter" :aria-pressed="recents">
          <svg viewBox="0 0 16 16" width="16" height="16" style="opacity: inherit">
            <path fill="currentColor" d="M1.5 8a6.5 6.5 0 1 1 13 0 6.5 6.5 0 0 1-13 0zM8 0a8 8 0 1 0 0 16A8 8 0 0 0 8 0zm.5 4.75a.75.75 0 0 0-1.5 0v3.5a.75.75 0 0 0 .37.65l2.5 1.5a.75.75 0 1 0 .76-1.3L8.5 7.87V4.75z"/>
          </svg>
        </Button>
        <Button variant="ghost" size="icon" class="no-snippets-toggle" :class="{ active: noSnippets }" @click="toggleNoSnippets" aria-label="Hide snippets" :aria-pressed="noSnippets">
          <span class="no-snippets-icon">✂️</span>
        </Button>
        <Button variant="ghost" size="icon" class="favourites-toggle" :class="{ active: showFavourites }" @click="showFavourites = !showFavourites" aria-label="Show favourites" :aria-pressed="showFavourites">
          <svg viewBox="0 0 16 16" width="16" height="16">
            <path v-if="showFavourites" fill="currentColor" d="M7.655 14.916 3 10.449a4.004 4.004 0 0 1 0-5.797 4.006 4.006 0 0 1 5.83.32 4.007 4.007 0 0 1 5.83-.32 4.005 4.005 0 0 1 0 5.797l-4.655 4.467a.75.75 0 0 1-1.35 0z"/>
            <path v-else fill="currentColor" d="m8 14.25.345.666a.75.75 0 0 1-.69 0l-.008-.004-.018-.01a7.152 7.152 0 0 1-.31-.17 22.055 22.055 0 0 1-3.434-2.414C2.045 10.731 0 8.35 0 5.5 0 2.836 2.086 1 4.25 1 5.797 1 7.153 1.802 8 3.02 8.847 1.802 10.203 1 11.75 1 13.914 1 16 2.836 16 5.5c0 2.85-2.045 5.231-3.885 6.818a22.066 22.066 0 0 1-3.744 2.584l-.018.01-.006.003h-.002ZM4.25 2.5c-1.336 0-2.75 1.164-2.75 3 0 2.15 1.58 4.144 3.365 5.682A20.58 20.58 0 0 0 8 13.393a20.58 20.58 0 0 0 3.135-2.211C12.92 9.644 14.5 7.65 14.5 5.5c0-1.836-1.414-3-2.75-3-1.373 0-2.609.986-3.029 2.456a.749.749 0 0 1-1.442 0C6.859 3.486 5.623 2.5 4.25 2.5Z"/>
          </svg>
        </Button>
      </div>
      <!-- Search result count -->
      <div v-if="isSearching" class="search-result-count">
        <span v-if="searchResultCount > 0">{{ searchResultCount }} result{{ searchResultCount === 1 ? '' : 's' }}</span>
        <span v-else>No results</span>
      </div>
    </div>

    <!-- Favourites view: songs favourited for this artist, grouped by era -->
    <template v-if="showFavourites">
      <div v-if="artistFavouritesByEra.length === 0" class="no-results">
        No favourites yet — click the ♥ on any song to save it here
      </div>
      <div v-else class="search-results">
        <template v-for="group in artistFavouritesByEra" :key="group.eraName">
          <div class="era-group-header">
            <span class="era-badge-pill" :style="eraColorStyle({ name: group.eraName, art_url: group.eraArt })">{{ group.eraName }}</span>
            <div class="era-group-line"></div>
          </div>
          <div
            v-for="entry in group.entries"
            :key="entry.key"
            class="search-result-row"
          >
            <div class="search-result-version">
              <SongRow
                :song="entry.song"
                :artist-name="artist.name"
                :artist-slug="artist.slug"
                :source-url="artist.source_url ?? null"
                :era-name="entry.eraName"
                :era-art="entry.eraArt ?? undefined"
                :expanded="false"
              />
            </div>
          </div>
        </template>
      </div>
    </template>

    <!-- Recents view: flat list sorted by leak date -->
    <!-- Recents view: flat list sorted by leak date (optionally filtered by search + best-of) -->
    <template v-else-if="recents">
      <div v-if="recentResults.length === 0" class="no-results">
        <template v-if="isSearching">No recent entries matching "{{ searchQuery }}"</template>
        <template v-else>No entries with leak dates found</template>
      </div>
      <div v-else class="search-results">
        <template
          v-for="(result, idx) in visibleRecentResults"
          :key="`r:${result.era.name}:${result.version.name}:${idx}`"
        >
          <!-- Era group header — only shown on first result per era -->
          <div
            v-if="idx === 0 || visibleRecentResults[idx - 1].era.name !== result.era.name"
            class="era-group-header"
          >
            <span class="era-badge-pill" :style="eraColorStyle(result.era)">{{ result.era.name }}</span>
            <div class="era-group-line"></div>
          </div>
          <div class="search-result-row">
            <div class="search-result-meta">
              <span v-if="result.version.leak_date" class="leak-date-badge">{{ result.version.leak_date }}</span>
            </div>
            <div class="search-result-version">
              <VersionRow
                :version="result.version"
                :artist-name="artist.name"
                :artist-slug="artist.slug"
                :source-url="artist.source_url ?? null"
                :era-name="result.era.name"
                :era-art="result.era.art_url"
                :hide-alt-titles="true"
              />
            </div>
          </div>
        </template>
        <!-- Sentinel: triggers loading more results when scrolled into view -->
        <div
          v-if="recentsLimit < recentResults.length"
          ref="recentsSentinel"
          class="recents-sentinel"
          aria-hidden="true"
        ></div>
      </div>
    </template>

    <!-- Search results: flat version list (optionally filtered by best-of) -->
    <template v-else-if="isSearching">
      <div v-if="flatSearchResults.length === 0" class="no-results">
        No results for "{{ searchQuery }}"
      </div>
      <div v-else class="search-results">
        <template
          v-for="(result, idx) in flatSearchResults"
          :key="`s:${result.era.name}:${result.version.name}:${idx}`"
        >
          <!-- Era group header — only shown on first result per era -->
          <div
            v-if="idx === 0 || flatSearchResults[idx - 1].era.name !== result.era.name"
            class="era-group-header"
          >
            <span class="era-badge-pill" :style="eraColorStyle(result.era)">{{ result.era.name }}</span>
            <div class="era-group-line"></div>
          </div>
          <div class="search-result-row">
            <div class="search-result-version">
              <VersionRow
                :version="result.version"
                :artist-name="artist.name"
                :artist-slug="artist.slug"
                :source-url="artist.source_url ?? null"
                :era-name="result.era.name"
                :era-art="result.era.art_url"
                :hide-alt-titles="true"
              />
            </div>
          </div>
        </template>
      </div>
    </template>

    <!-- Normal era browsing -->
    <div v-else class="eras-list" role="list" aria-label="Eras">
      <div v-if="filteredEras.length === 0" class="no-results">No eras with Best Of or Special tracks found</div>
      <div v-for="(era, eraIdx) in filteredEras" :key="era.name" class="era-block" :ref="setEraBlockRef(era.name)" v-auto-animate="{ duration: 280, easing: 'cubic-bezier(0.4, 0, 0.2, 1)' }">
        <EraCard
          :era="era"
          :expanded="isEraExpanded(era.name)"
          :index="eraIdx"
          :best-of="bestOf"
          @click="handleToggleEra(era.name)"
        />

        <!-- Expanded songs panel — animated by v-auto-animate on the parent -->
        <div v-if="isEraExpanded(era.name)" class="era-songs-panel" :style="{ '--era-accent': eraColorStyle(era).borderColor }">
          <SongList
            :sections="eraSections(era)"
            :songs="filteredSongs(era)"
            :artist-name="artist.name"
            :artist-slug="artist.slug"
            :source-url="artist.source_url ?? null"
            :era-name="era.name"
            :era-art="era.art_url"
            :empty-message="bestOf ? 'No Best Of or Special tracks in this era' : 'No songs in this era'"
          />
        </div>
      </div>
    </div>

    <!-- Scroll-to-top button (mobile) -->
    <ScrollToTop :visible="showScrollTop" @click="scrollToTop" />

    <!-- Shared context menu (single instance for all rows) -->
    <ContextMenu
      v-if="contextMenuState"
      :x="contextMenuState.x"
      :y="contextMenuState.y"
      :song="contextMenuState.song"
      :version="contextMenuState.version"
      :artist-name="contextMenuState.artistName"
      :artist-slug="contextMenuState.artistSlug"
      :source-url="contextMenuState.sourceUrl"
      :era-name="contextMenuState.eraName"
      :era-art="contextMenuState.eraArt"
      @close="closeContextMenu"
      @show-description="handleShowDescription"
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

/* Search */
.search-bar-wrap {
  margin-bottom: 20px;
}

.search-result-count {
  margin-top: 6px;
  padding-left: 4px;
  font-size: 11.5px;
  color: var(--text-dim);
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

.best-of-toggle,
.recents-toggle,
.no-snippets-toggle,
.favourites-toggle {
  flex-shrink: 0;
  opacity: 0.35;
  border: 1px solid transparent;
  min-width: 44px;
  min-height: 44px;
  -webkit-tap-highlight-color: transparent;
}

.best-of-toggle:hover,
.recents-toggle:hover,
.no-snippets-toggle:hover,
.favourites-toggle:hover {
  opacity: 0.7;
}

.best-of-toggle.active {
  opacity: 1;
  background: rgba(255, 215, 0, 0.20);
  border-color: rgba(255, 215, 0, 0.45);
  box-shadow: 0 0 0 1px rgba(255, 215, 0, 0.3);
}

.recents-toggle.active {
  opacity: 1;
  background: rgba(88, 166, 255, 0.20);
  border-color: rgba(88, 166, 255, 0.45);
  box-shadow: 0 0 0 1px rgba(88, 166, 255, 0.3);
}

.no-snippets-toggle.active {
  opacity: 1;
  background: rgba(239, 68, 68, 0.20);
  border-color: rgba(239, 68, 68, 0.45);
  box-shadow: 0 0 0 1px rgba(239, 68, 68, 0.3);
}

.favourites-toggle.active {
  opacity: 1;
  color: var(--favourite-color, #e84057);
  background: rgba(232, 64, 87, 0.15);
  border-color: rgba(232, 64, 87, 0.40);
  box-shadow: 0 0 0 1px rgba(232, 64, 87, 0.25);
}

.no-snippets-icon {
  font-size: 15px;
  line-height: 1;
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
  border-top: 2px solid var(--era-accent, var(--accent-color));
  border-radius: 0 0 12px 12px;
  padding: 0 16px 16px;
  overflow: hidden;
  min-height: 0;
}


/* Search results (flat list) */
.search-results {
  display: flex;
  flex-direction: column;
}

.recents-sentinel {
  height: 1px;
}

.era-group-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 0 4px;
}

.era-group-header:first-child {
  padding-top: 4px;
}

.era-group-line {
  flex: 1;
  height: 1px;
  background: rgba(255, 255, 255, 0.06);
}

.search-result-row {
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  padding: 4px 0;
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
  .era-badge-pill { font-size: 8px; padding: 2px 6px; }
}
</style>
