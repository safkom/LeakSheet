<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import TrackerInput from './components/TrackerInput.vue'
import ArtistView from './components/ArtistView.vue'
import PlayerBar from './components/PlayerBar.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Toaster } from '@/components/ui/sonner'
import { parseSheet } from './composables/useApi'
import { playerState, togglePlay, seekTo } from './composables/usePlayer'

const activeArtist = ref(null)
const loading = ref(false)
const loadingUrl = ref('')
const error = ref('')
// Multi-artist: track loaded tracker history (persisted in localStorage)
const STORAGE_KEY = 'leaksheet_recent_trackers'

function loadStoredHistory() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveHistory(entries) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
  } catch { /* quota exceeded — ignore */ }
}

const trackerHistory = ref(loadStoredHistory())

const hasPlayer = computed(() => playerState.track !== null)

async function handleParse(url) {
  loading.value = true
  loadingUrl.value = url
  error.value = ''
  try {
    const data = await parseSheet(url)
    activeArtist.value = data
    // Preload era artwork images for faster rendering
    _preloadEraImages(data)
    // Add to history (or update existing) and persist
    const existing = trackerHistory.value.find(h => h.source_url === url)
    if (existing) {
      existing.name = data.name
      existing.total_songs = data.total_songs
    } else {
      trackerHistory.value.unshift({
        name: data.name,
        source_url: url,
        total_songs: data.total_songs,
      })
    }
    saveHistory(trackerHistory.value)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function goHome() {
  activeArtist.value = null
}

/** Preload era artwork images so they're cached before scrolling */
function _preloadEraImages(artist) {
  if (!artist?.eras) return
  for (const era of artist.eras.slice(0, 10)) {
    if (!era.art_url) continue
    const url = era.art_url.startsWith('//') ? 'https:' + era.art_url : era.art_url
    if (url.startsWith('http')) {
      const img = new Image()
      img.src = `/api/image-proxy?url=${encodeURIComponent(url)}`
    }
  }
}

function loadFromHistory(entry) {
  handleParse(entry.source_url)
}

function clearHistory() {
  trackerHistory.value = []
  localStorage.removeItem(STORAGE_KEY)
}

// ---------------------------------------------------------------------------
// Keyboard controls
// ---------------------------------------------------------------------------

function handleKeyboard(e) {
  // Don't intercept when typing in input fields
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return

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
    // they conflict with normal page scrolling. Volume is controlled
    // via the slider in the player bar instead.
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
  <header class="app-header">
    <button class="logo-btn" @click="goHome">
      <span class="logo-text">Leak</span><span class="logo-accent">Sheet</span>
    </button>
    <div v-if="activeArtist" class="header-artist">
      {{ activeArtist.name }}
    </div>
    <div v-else-if="loading" class="header-loading">
      <span class="header-loading-dot"></span>
      Parsing&hellip;
    </div>
  </header>

  <main class="app-main" :class="{ 'has-player': hasPlayer }">
    <!-- Landing / Home -->
    <div v-if="!activeArtist && !loading" class="landing">
      <div class="landing-hero">
        <h1><span class="hero-text">Leak</span><span class="hero-accent">Sheet</span></h1>
        <p class="hero-sub">Parse and explore unreleased music trackers</p>
      </div>

      <TrackerInput :loading="loading" @parse="handleParse" />

      <p v-if="error" class="error-msg">{{ error }}</p>

      <!-- History on landing page -->
      <div v-if="trackerHistory.length" class="landing-history">
        <div class="history-header">
          <h3 class="history-title">Recent Trackers</h3>
          <button class="history-clear" @click="clearHistory">Clear</button>
        </div>
        <Button
          v-for="entry in trackerHistory"
          :key="entry.source_url"
          variant="outline"
          class="history-card"
          @click="loadFromHistory(entry)"
        >
          <span class="history-card-name">{{ entry.name }}</span>
          <span class="history-card-meta">{{ entry.total_songs }} songs</span>
        </Button>
      </div>
    </div>

    <!-- Loading state -->
    <div v-else-if="loading" class="loading-view">
      <div class="loading-status">
        <div class="loading-spinner-ring">
          <svg viewBox="0 0 24 24" width="32" height="32" class="loading-spin">
            <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="50 14" />
          </svg>
        </div>
        <p class="loading-title">Parsing tracker&hellip;</p>
        <p class="loading-url">{{ loadingUrl }}</p>
      </div>

      <!-- Skeleton mimicking ArtistView -->
      <div class="loading-skeleton">
        <Skeleton class="h-7 w-44 mb-1 rounded-md" />
        <Skeleton class="h-4 w-20 mb-5 rounded" />

        <!-- Search bar skeleton -->
        <Skeleton class="h-10 w-full mb-5 rounded-lg" />

        <!-- Era card skeletons -->
        <div class="skeleton-eras">
          <div v-for="i in 6" :key="i" class="skeleton-era-card">
            <Skeleton class="skeleton-era-art" />
            <div class="skeleton-era-info">
              <Skeleton class="h-4 rounded" :style="{ width: [65,80,55,72,60,48][i-1] + '%' }" />
              <Skeleton class="h-3 w-16 rounded mt-1.5" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Artist detail view -->
    <ArtistView v-else :artist="activeArtist" />
  </main>

  <PlayerBar v-if="hasPlayer" />
  <Toaster position="bottom-center" :offset="hasPlayer ? 80 : 16" />
</template>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  height: var(--header-height);
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 16px;
}

.logo-btn {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.5px;
}
.logo-text { color: var(--text-primary); }
.logo-accent { color: var(--accent-color); }

.header-artist {
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
}

.header-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-dim);
  font-size: 13px;
}

.header-loading-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-color);
  animation: pulse-dot 1.2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}

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
  color: #f85149;
  text-align: center;
  margin-top: 12px;
  font-size: 13px;
}

/* Landing history cards */
.landing-history {
  margin-top: 40px;
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
  color: #f85149;
  background: rgba(248, 81, 73, 0.1);
}

.history-card {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: auto;
  padding: 12px 16px;
  margin-bottom: 8px;
  white-space: normal;
}

.history-card:hover {
  border-color: var(--accent-color);
}

.history-card-name {
  font-size: 14px;
  font-weight: 500;
  text-align: left;
}

/* Loading view */
.loading-view {
  max-width: 900px;
  margin: 0 auto;
  padding: 48px 20px 40px;
}

.loading-status {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin-bottom: 48px;
}

.loading-spinner-ring {
  color: var(--accent-color);
  margin-bottom: 4px;
}

.loading-spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.loading-url {
  font-size: 12px;
  color: var(--text-dim);
  max-width: 420px;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Skeleton layout matching ArtistView */
.loading-skeleton {
  max-width: 900px;
  margin: 0 auto;
}

.skeleton-eras {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-era-card {
  display: flex;
  align-items: center;
  gap: 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 14px 16px;
}

.skeleton-era-art {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  flex-shrink: 0;
}

.skeleton-era-info {
  flex: 1;
  min-width: 0;
}

.history-card-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

@media (max-width: 640px) {
  .landing { padding: 32px 16px 24px; }
  .landing-hero h1 { font-size: 36px; }
}
</style>
