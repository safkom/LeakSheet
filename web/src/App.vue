<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import TrackerInput from './components/TrackerInput.vue'
import ArtistView from './components/ArtistView.vue'
import RecentTrackerCard from './components/RecentTrackerCard.vue'
const PlayerBar = defineAsyncComponent(() => import('./components/PlayerBar.vue'))
const FavouritesPanel = defineAsyncComponent(() => import('./components/FavouritesPanel.vue'))
import { Toaster } from '@/components/ui/sonner'
import { parseSheet, USER_ABORT } from './composables/useApi'
import { playerState, togglePlay, seekTo, enhanceGoogleImageUrl } from './composables/usePlayer'
import { extractAndCacheEraColors } from './composables/useEraColors'
import { favourites } from './composables/useFavourites'
import { recentTrackers, saveRecentTracker, clearRecentTrackers } from './composables/useRecentTrackers'

const activeArtist = ref(null)
const showFavouritesPanel = ref(false)
const loading = ref(false)
const loadingUrl = ref('')
const error = ref('')
const lastUrl = ref('')

const hasPlayer = computed(() => playerState.track !== null)

async function handleParse(url: string) {
  loading.value = true
  loadingUrl.value = url
  lastUrl.value = url
  error.value = ''
  try {
    const data = await parseSheet(url)
    // Wait for all era cover images to load silently, then reveal
    await _waitForImages(data)
    activeArtist.value = data
    saveRecentTracker(data)
  } catch (e) {
    // Silently ignore user-initiated cancellations (user submitted a new URL).
    // We check object identity against our sentinel so that timeouts or other
    // AbortError variants always surface as an error message instead of
    // disappearing silently.
    if (e === USER_ABORT) return
    // TimeoutError means the request took too long — offer a retry
    if (e?.name === 'TimeoutError' || e?.message?.includes('timeout') || e?.message?.includes('timed out')) {
      error.value = 'Request timed out — check your connection and try again'
    } else {
      error.value = e instanceof Error ? e.message : String(e)
    }
  } finally {
    loading.value = false
    loadingUrl.value = ''
  }
}

function goHome() {
  activeArtist.value = null
}

/** Wait for all era cover images to load, extracting colors as they arrive.
 * Resolves when every image finishes (or fails) — hard timeout of 6s as a safety net. */
function _waitForImages(artist) {
  if (!artist?.eras) return Promise.resolve()
  const artEras = artist.eras.filter(era => {
    if (!era.art_url) return false
    const u = era.art_url.startsWith('//') ? 'https:' + era.art_url : era.art_url
    return u.startsWith('http')
  })
  if (!artEras.length) return Promise.resolve()

  const promises = artEras.map(era => new Promise(resolve => {
    const url = era.art_url.startsWith('//') ? 'https:' + era.art_url : era.art_url
    const enhanced = enhanceGoogleImageUrl(url)
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      extractAndCacheEraColors(era.name, img)
      resolve(img)
    }
    img.onerror = () => resolve(null)
    img.src = `/api/image-proxy?url=${encodeURIComponent(enhanced)}`
  }))

  const timeout = new Promise(resolve => setTimeout(resolve, 6000))
  return Promise.race([Promise.all(promises), timeout])
}

function loadFromHistory(entry) {
  handleParse(entry.source_url)
}

// ---------------------------------------------------------------------------
// Artist discovery
// ---------------------------------------------------------------------------

const DISCOVERY_URL = 'https://assets.artistgrid.cx/artists.ndjson'

const discoveryOpen = ref(false)
const discoveryArtists = ref([])
const discoverySearch = ref('')
const discoveryLoading = ref(false)
const discoveryError = ref('')

async function loadDiscovery() {
  if (discoveryOpen.value) {
    discoveryOpen.value = false
    return
  }
  discoveryOpen.value = true
  if (discoveryArtists.value.length) return
  discoveryLoading.value = true
  discoveryError.value = ''
  try {
    const res = await fetch(DISCOVERY_URL)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const text = await res.text()
    discoveryArtists.value = text.trim().split('\n')
      .filter(Boolean)
      .map(line => { try { return JSON.parse(line) } catch { return null } })
      .filter(Boolean)
      .sort((a, b) => {
        // Best-rated first, then alphabetical
        if (a.best && !b.best) return -1
        if (!a.best && b.best) return 1
        return a.name.localeCompare(b.name)
      })
  } catch (e) {
    discoveryError.value = `Could not load artist list: ${e.message}`
  } finally {
    discoveryLoading.value = false
  }
}

const _debouncedDiscoverySearch = ref('')
let _discoveryDebounceTimer: ReturnType<typeof setTimeout> | null = null
watch(discoverySearch, (val) => {
  if (_discoveryDebounceTimer) clearTimeout(_discoveryDebounceTimer)
  const trimmed = val.trim()
  if (!trimmed) { _debouncedDiscoverySearch.value = ''; return }
  _discoveryDebounceTimer = setTimeout(() => {
    _debouncedDiscoverySearch.value = trimmed.toLowerCase()
  }, 150)
})

// Pre-lowercased names for efficient search filtering
const _discoveryNamesLower = computed(() =>
  discoveryArtists.value.map(a => ({ artist: a, lower: a.name.toLowerCase() }))
)

const filteredDiscovery = computed(() => {
  const q = _debouncedDiscoverySearch.value
  if (!q) return discoveryArtists.value
  return _discoveryNamesLower.value.filter(({ lower }) => lower.includes(q)).map(({ artist }) => artist)
})

const discoveryLoadingUrl = ref('')

function pickDiscoveryArtist(artist) {
  discoveryLoadingUrl.value = artist.url
  handleParse(artist.url).finally(() => {
    discoveryLoadingUrl.value = ''
    discoverySearch.value = ''
    discoveryOpen.value = false
  })
}

// ---------------------------------------------------------------------------
// Keyboard controls
// ---------------------------------------------------------------------------

function handleKeyboard(e) {
  // Don't intercept when typing in input fields or contenteditable elements
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return

  switch (e.code) {
    case 'Space':
      if (playerState.track) {
        e.preventDefault()
        togglePlay()
      }
      break
    case 'ArrowLeft':
      if (playerState.track && playerState.streamUrl) {
        e.preventDefault()
        seekTo(Math.max(0, playerState.currentTime - 5))
      }
      break
    case 'ArrowRight':
      if (playerState.track && playerState.streamUrl) {
        e.preventDefault()
        seekTo(playerState.currentTime + 5)
      }
      break
    // Note: ArrowUp/ArrowDown intentionally not intercepted —
    // they conflict with normal page scrolling.
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeyboard)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeyboard)
})
</script>

<template>
  <main class="app-main" :class="{ 'has-player': hasPlayer }">
    <Transition name="content-fade" mode="out-in">

      <!-- Artist detail view -->
      <ArtistView v-if="activeArtist" :artist="activeArtist" key="artist" @back="goHome" />

      <!-- Landing / Home (stays visible while loading) -->
      <div v-else class="landing" key="landing">
        <div class="landing-hero">
          <h1><span class="hero-text">Leak</span><span class="hero-accent">Sheet</span></h1>
          <p class="hero-sub">Parse and explore unreleased music trackers</p>
        </div>

        <TrackerInput :loading="loading" @parse="handleParse" />

        <p v-if="error" class="error-msg">
          {{ error }}
          <button v-if="lastUrl" class="retry-btn" @click="handleParse(lastUrl)">Retry</button>
        </p>

        <!-- Artist discovery + Favourites -->
        <div class="discovery-row">
          <button class="discovery-toggle" :class="{ active: discoveryOpen }" @click="loadDiscovery">
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path fill="currentColor" d="M1.5 2.75a.75.75 0 0 1 .75-.75h11.5a.75.75 0 0 1 0 1.5H2.25a.75.75 0 0 1-.75-.75zm0 5a.75.75 0 0 1 .75-.75h11.5a.75.75 0 0 1 0 1.5H2.25a.75.75 0 0 1-.75-.75zm0 5a.75.75 0 0 1 .75-.75h11.5a.75.75 0 0 1 0 1.5H2.25a.75.75 0 0 1-.75-.75z"/>
            </svg>
            Browse Artists
            <svg class="discovery-chevron" :class="{ open: discoveryOpen }" viewBox="0 0 16 16" width="10" height="10" aria-hidden="true">
              <path fill="currentColor" d="M4.427 7.427l3.396 3.396a.25.25 0 0 0 .354 0l3.396-3.396A.25.25 0 0 0 11.396 7H4.604a.25.25 0 0 0-.177.427z"/>
            </svg>
          </button>
          <!-- Favourites button — shown when there are saved songs -->
          <button
            v-if="favourites.length > 0"
            class="favourites-panel-btn"
            :class="{ active: showFavouritesPanel }"
            aria-label="Open favourites"
            @click="showFavouritesPanel = !showFavouritesPanel"
          >
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path v-if="showFavouritesPanel" fill="currentColor" d="M7.655 14.916 3 10.449a4.004 4.004 0 0 1 0-5.797 4.006 4.006 0 0 1 5.83.32 4.007 4.007 0 0 1 5.83-.32 4.005 4.005 0 0 1 0 5.797l-4.655 4.467a.75.75 0 0 1-1.35 0z"/>
              <path v-else fill="currentColor" d="m8 14.25.345.666a.75.75 0 0 1-.69 0l-.008-.004-.018-.01a7.152 7.152 0 0 1-.31-.17 22.055 22.055 0 0 1-3.434-2.414C2.045 10.731 0 8.35 0 5.5 0 2.836 2.086 1 4.25 1 5.797 1 7.153 1.802 8 3.02 8.847 1.802 10.203 1 11.75 1 13.914 1 16 2.836 16 5.5c0 2.85-2.045 5.231-3.885 6.818a22.066 22.066 0 0 1-3.744 2.584l-.018.01-.006.003h-.002ZM4.25 2.5c-1.336 0-2.75 1.164-2.75 3 0 2.15 1.58 4.144 3.365 5.682A20.58 20.58 0 0 0 8 13.393a20.58 20.58 0 0 0 3.135-2.211C12.92 9.644 14.5 7.65 14.5 5.5c0-1.836-1.414-3-2.75-3-1.373 0-2.609.986-3.029 2.456a.749.749 0 0 1-1.442 0C6.859 3.486 5.623 2.5 4.25 2.5Z"/>
            </svg>
            Favourites
            <span class="fav-count-badge">{{ favourites.length }}</span>
          </button>
        </div>

        <Transition name="discovery-expand">
          <div v-if="discoveryOpen" class="discovery-panel">
            <div v-if="discoveryLoading" class="discovery-loading">
              <span class="history-spinner" />
              <span>Loading artists...</span>
            </div>
            <p v-else-if="discoveryError" class="error-msg" style="margin: 0">{{ discoveryError }}</p>
            <template v-else>
              <input
                v-model="discoverySearch"
                class="discovery-search"
                placeholder="Search artists…"
                autocomplete="off"
                spellcheck="false"
              />
              <p v-if="filteredDiscovery.length === 0" class="discovery-empty">No artists found.</p>
              <div class="discovery-list">
                <button
                  v-for="artist in filteredDiscovery"
                  :key="artist.url"
                  class="discovery-item"
                  :class="{ 'discovery-item-loading': discoveryLoadingUrl === artist.url }"
                  :disabled="loading"
                  @click="pickDiscoveryArtist(artist)"
                >
                  <span class="discovery-name">{{ artist.name }}</span>
                  <span class="discovery-meta">
                    <span v-if="discoveryLoadingUrl === artist.url" class="history-spinner" />
                    <template v-else>
                      <span v-if="artist.best" class="discovery-best" title="Curated tracker">★</span>
                      <span
                        class="discovery-status"
                        :class="artist.links_work === 1 ? 'status-ok' : artist.links_work === 2 ? 'status-partial' : 'status-unknown'"
                        :title="artist.links_work === 1 ? 'All links working' : artist.links_work === 2 ? 'Some links working' : 'Link status unknown'"
                        :aria-label="artist.links_work === 1 ? 'All links working' : artist.links_work === 2 ? 'Some links working' : 'Link status unknown'"
                        role="img"
                      >●</span>
                    </template>
                  </span>
                </button>
              </div>
            </template>
          </div>
        </Transition>

        <!-- History on landing page -->
        <div v-if="recentTrackers.length" class="landing-history">
          <div class="history-header">
            <h3 class="history-title">Recent Trackers</h3>
            <button class="history-clear" @click="clearRecentTrackers">Clear</button>
          </div>
          <RecentTrackerCard
            v-for="entry in recentTrackers"
            :key="entry.source_url"
            :entry="entry"
            :disabled="loading"
            @click="loadFromHistory(entry)"
          />
        </div>
      </div>

    </Transition>
  </main>

  <FavouritesPanel v-if="showFavouritesPanel" @close="showFavouritesPanel = false" />
  <PlayerBar v-if="hasPlayer" />
  <Toaster position="bottom-center" :offset="hasPlayer ? 80 : 16" />
</template>

<style scoped>
.app-main {
  flex: 1;
  padding-bottom: 20px;
}
.app-main.has-player {
  padding-bottom: calc(var(--player-height) + env(safe-area-inset-bottom, 0px) + 20px);
}

/* Landing */
.landing {
  max-width: 720px;
  margin: 0 auto;
  padding: 60px 20px 40px;
}

.landing-hero {
  text-align: center;
  margin-bottom: 40px;
}

.landing-hero h1 {
  font-family: var(--font-display);
  font-size: 48px;
  font-weight: 800;
  letter-spacing: -2px;
  margin-bottom: 8px;
  display: inline-block;
}
.hero-text { color: var(--text-primary); }
.hero-accent {
  background: linear-gradient(135deg, var(--accent-color), #58a6ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-sub {
  color: var(--text-secondary);
  font-size: 16px;
}

.error-msg {
  color: var(--color-error);
  text-align: center;
  margin-top: 12px;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
}

.retry-btn {
  font-size: 12px;
  color: var(--color-error);
  border: 1px solid rgba(248, 81, 73, 0.4);
  border-radius: 4px;
  padding: 2px 10px;
  transition: background 0.1s, border-color 0.1s;
  white-space: nowrap;
}

.retry-btn:hover {
  background: rgba(248, 81, 73, 0.12);
  border-color: rgba(248, 81, 73, 0.7);
}

/* Artist discovery + Favourites row */
.discovery-row {
  margin-top: 20px;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
}

.discovery-toggle {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 18px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.discovery-toggle:hover,
.discovery-toggle.active {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.85);
}

.favourites-panel-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 18px;
  background: rgba(232, 64, 87, 0.08);
  border: 1px solid rgba(232, 64, 87, 0.25);
  border-radius: 8px;
  color: rgba(232, 64, 87, 0.7);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.favourites-panel-btn:hover,
.favourites-panel-btn.active {
  background: rgba(232, 64, 87, 0.15);
  border-color: rgba(232, 64, 87, 0.5);
  color: var(--favourite-color, #e84057);
}

.fav-count-badge {
  background: rgba(232, 64, 87, 0.2);
  color: var(--favourite-color, #e84057);
  font-size: 11px;
  font-weight: 600;
  border-radius: 10px;
  padding: 1px 6px;
  min-width: 18px;
  text-align: center;
}

.discovery-chevron {
  transition: transform 0.2s ease;
  opacity: 0.6;
}

.discovery-chevron.open {
  transform: rotate(180deg);
}

.discovery-panel {
  margin-top: 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.02);
  overflow: hidden;
  padding: 12px;
}

.discovery-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 4px;
  color: var(--text-secondary);
  font-size: 13px;
}

.discovery-search {
  width: 100%;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
  margin-bottom: 10px;
  outline: none;
  transition: border-color 0.15s;
  box-sizing: border-box;
}

.discovery-search:focus {
  border-color: rgba(255, 255, 255, 0.25);
}

.discovery-empty {
  text-align: center;
  color: var(--text-dim);
  font-size: 13px;
  padding: 12px 0;
}

.discovery-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 320px;
  overflow-y: auto;
}

.discovery-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 12px;
  border-radius: 7px;
  border: 1px solid transparent;
  background: none;
  color: var(--text-primary);
  font-size: 14px;
  text-align: left;
  cursor: pointer;
  transition: all 0.1s;
}

.discovery-item:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.07);
}

.discovery-item:disabled {
  opacity: 0.5;
  cursor: default;
}

.discovery-item-loading {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.1);
}

.discovery-name {
  font-weight: 500;
}

.discovery-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.discovery-best {
  color: #e3b341;
  font-size: 12px;
}

.discovery-status {
  font-size: 9px;
}

.status-ok { color: #3fb950; }
.status-partial { color: #d29922; }
.status-unknown { color: rgba(255, 255, 255, 0.2); }

.discovery-expand-enter-active,
.discovery-expand-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.discovery-expand-enter-from,
.discovery-expand-leave-to {
  opacity: 0;
  transform: translateY(-6px);
  -webkit-transform: translateY(-6px);
}

/* Landing history cards */
.landing-history {
  margin-top: 40px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.history-title {
  font-size: 13px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.history-clear {
  font-size: 12px;
  color: var(--text-dim);
  padding: 2px 8px;
  border-radius: 4px;
  transition: color 0.1s, background 0.1s;
}

.history-clear:hover {
  color: var(--color-error);
  background: rgba(248, 81, 73, 0.1);
}

/* Content fade transition */
.content-fade-enter-active {
  transition: opacity 0.25s ease, -webkit-transform 0.25s ease, transform 0.25s ease;
  -webkit-transition: opacity 0.25s ease, -webkit-transform 0.25s ease;
}
.content-fade-leave-active {
  transition: opacity 0.18s ease, -webkit-transform 0.18s ease, transform 0.18s ease;
  -webkit-transition: opacity 0.18s ease, -webkit-transform 0.18s ease;
}
.content-fade-enter-from {
  opacity: 0;
  -webkit-transform: translate3d(0, 8px, 0);
  transform: translate3d(0, 8px, 0);
}
.content-fade-leave-to {
  opacity: 0;
  -webkit-transform: translate3d(0, -6px, 0);
  transform: translate3d(0, -6px, 0);
}


.history-spinner {
  display: inline-block;
  width: 13px;
  height: 13px;
  border: 2px solid transparent;
  border-top-color: var(--accent-color);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 640px) {
  .landing { padding: 32px 16px 24px; }
  .landing-hero h1 { font-size: 36px; }
}
</style>
