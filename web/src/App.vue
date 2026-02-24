<script setup>
import { ref, computed } from 'vue'
import TrackerInput from './components/TrackerInput.vue'
import ArtistView from './components/ArtistView.vue'
import PlayerBar from './components/PlayerBar.vue'
import { listArtists, parseTracker, getArtist } from './composables/useApi.js'
import { playerState } from './composables/usePlayer.js'

const artists = ref([])
const activeArtist = ref(null)
const loading = ref(false)
const error = ref('')

const hasPlayer = computed(() => playerState.track !== null)

async function loadArtists() {
  try {
    artists.value = await listArtists()
  } catch (e) {
    // Silent — no artists loaded on startup is fine
  }
}

async function handleParse(url) {
  loading.value = true
  error.value = ''
  try {
    const summary = await parseTracker(url)
    await loadArtists()
    await selectArtist(summary.slug)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function selectArtist(slug) {
  loading.value = true
  error.value = ''
  try {
    activeArtist.value = await getArtist(slug)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function goHome() {
  activeArtist.value = null
}

// Load artists on mount
loadArtists()
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
    <div v-if="!activeArtist" class="landing">
      <div class="landing-hero">
        <h1><span class="hero-text">Leak</span><span class="hero-accent">Sheet</span></h1>
        <p class="hero-sub">Parse and explore unreleased music trackers</p>
      </div>

      <TrackerInput :loading="loading" @parse="handleParse" />

      <p v-if="error" class="error-msg">{{ error }}</p>

      <!-- Recent trackers -->
      <div v-if="artists.length" class="recent-section">
        <h3 class="section-title">Loaded Trackers</h3>
        <div class="artist-grid">
          <button
            v-for="a in artists"
            :key="a.slug"
            class="artist-card"
            @click="selectArtist(a.slug)"
          >
            <div class="artist-card-name">{{ a.name }}</div>
            <div class="artist-card-stats">
              {{ a.era_count }} eras · {{ a.total_songs }} songs
            </div>
          </button>
        </div>
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
  padding-bottom: calc(var(--player-height) + 20px);
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

.recent-section {
  margin-top: 48px;
}

.section-title {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 16px;
}

.artist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.artist-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px;
  text-align: left;
  transition: all 0.15s ease;
}
.artist-card:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
}

.artist-card-name {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 4px;
}

.artist-card-stats {
  color: var(--text-secondary);
  font-size: 12px;
}

@media (max-width: 640px) {
  .landing { padding: 32px 16px 24px; }
  .landing-hero h1 { font-size: 36px; }
  .artist-grid { grid-template-columns: 1fr; }
}
</style>
