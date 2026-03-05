<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import TrackerInput from './components/TrackerInput.vue'
import ArtistView from './components/ArtistView.vue'
import PlayerBar from './components/PlayerBar.vue'
import { Button } from '@/components/ui/button'
import { Toaster } from '@/components/ui/sonner'
import { parseSheet } from './composables/useApi'
import { playerState, togglePlay, seekTo, enhanceGoogleImageUrl } from './composables/usePlayer'
import { extractAndCacheEraColors } from './composables/useEraColors'

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
    // Wait for all era cover images to load silently, then reveal
    await _waitForImages(data)
    activeArtist.value = data
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
      // Cap history at 20 entries
      if (trackerHistory.value.length > 20) {
        trackerHistory.value.length = 20
      }
    }
    saveHistory(trackerHistory.value)
  } catch (e) {
    error.value = e.message
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
            :disabled="loading"
            @click="loadFromHistory(entry)"
          >
            <span class="history-card-name">{{ entry.name }}</span>
            <span class="history-card-right">
              <span v-if="loadingUrl === entry.source_url" class="history-spinner" />
              <span v-else class="history-card-meta">{{ entry.total_songs }} songs</span>
            </span>
          </Button>
        </div>
      </div>

    </Transition>
  </main>

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

/* Content fade transition */
.content-fade-enter-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.content-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.content-fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.content-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}


.history-card-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

.history-card-right {
  display: flex;
  align-items: center;
  flex-shrink: 0;
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
