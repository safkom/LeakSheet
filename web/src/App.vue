<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import TrackerInput from './components/TrackerInput.vue'
import ArtistView from './components/ArtistView.vue'
import PlayerBar from './components/PlayerBar.vue'
import { parseSheet } from './composables/useApi.js'
import { playerState, togglePlay, seekTo, setVolume } from './composables/usePlayer.js'

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

function loadFromHistory(entry) {
  handleParse(entry.source_url)
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
    case 'ArrowUp':
      if (playerState.track) {
        e.preventDefault()
        setVolume(Math.min(1, playerState.volume + 0.05))
      }
      break
    case 'ArrowDown':
      if (playerState.track) {
        e.preventDefault()
        setVolume(Math.max(0, playerState.volume - 0.05))
      }
      break
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
    <!-- Multi-artist history -->
    <div v-if="trackerHistory.length > 1" class="header-history">
      <button
        v-for="entry in trackerHistory"
        :key="entry.source_url"
        class="history-btn"
        :class="{ active: activeArtist?.name === entry.name }"
        @click="loadFromHistory(entry)"
      >
        {{ entry.name }}
      </button>
    </div>
  </header>

  <main class="app-main" :class="{ 'has-player': hasPlayer }">
    <!-- Landing / Home -->
    <div v-if="!activeArtist" class="landing">
      <div class="landing-hero">
        <h1><span class="hero-text">Leak</span><span class="hero-accent">Sheet</span></h1>
        <p class="hero-sub">Parse and explore unreleased music trackers</p>
      </div>

      <TrackerInput :loading="loading" @parse="handleParse" />

      <p v-if="error" class="error-msg">{{ error }}</p>

      <!-- History on landing page -->
      <div v-if="trackerHistory.length" class="landing-history">
        <h3 class="history-title">Recent Trackers</h3>
        <button
          v-for="entry in trackerHistory"
          :key="entry.source_url"
          class="history-card"
          @click="loadFromHistory(entry)"
        >
          <span class="history-card-name">{{ entry.name }}</span>
          <span class="history-card-meta">{{ entry.total_songs }} songs</span>
        </button>
      </div>
    </div>

    <!-- Artist detail view -->
    <ArtistView v-else :artist="activeArtist" />
  </main>

  <PlayerBar v-if="hasPlayer" />
</template>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  height: var(--header-height);
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 16px;
}

.logo-btn {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.5px;
}
.logo-text { color: var(--text-primary); }
.logo-accent { color: var(--accent); }

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
  font-size: 48px;
  font-weight: 700;
  letter-spacing: -1.5px;
  margin-bottom: 8px;
}
.hero-text { color: var(--text-primary); }
.hero-accent { color: var(--accent); }

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

/* Multi-artist history (header tabs) */
.header-history {
  display: flex;
  gap: 4px;
  margin-left: auto;
}

.history-btn {
  padding: 4px 12px;
  font-size: 12px;
  color: var(--text-secondary);
  border-radius: 12px;
  background: transparent;
  transition: background 0.15s, color 0.15s;
}
.history-btn:hover { background: rgba(255,255,255,0.06); color: var(--text-primary); }
.history-btn.active { background: rgba(255,255,255,0.1); color: var(--accent); }

/* Landing history cards */
.landing-history {
  margin-top: 40px;
}

.history-title {
  font-size: 13px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

.history-card {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 8px;
  color: var(--text-primary);
  transition: background 0.15s, border-color 0.15s;
}
.history-card:hover {
  background: rgba(255,255,255,0.04);
  border-color: var(--accent);
}

.history-card-name {
  font-size: 14px;
  font-weight: 500;
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
