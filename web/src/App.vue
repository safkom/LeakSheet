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
    <div v-else-if="loading" class="landing">
      <div class="loading-skeleton">
        <Skeleton class="h-8 w-48 mb-4" />
        <Skeleton class="h-5 w-32 mb-8" />
        <div class="skeleton-eras">
          <Skeleton v-for="i in 5" :key="i" class="h-24 w-full rounded-xl" />
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

/* Skeleton loading */
.loading-skeleton {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px 20px;
}

.skeleton-eras {
  display: flex;
  flex-direction: column;
  gap: 12px;
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
