<script setup>
import { ref, computed } from 'vue'
import EraCard from './EraCard.vue'
import SongList from './SongList.vue'
import { getEra } from '../composables/useApi.js'

const props = defineProps({
  artist: Object,
})

const expandedEra = ref(null) // index of currently expanded era
const eraData = ref(null)     // full era data (with songs)
const loadingEra = ref(false)

const eras = computed(() => props.artist?.eras || [])

async function toggleEra(index) {
  if (expandedEra.value === index) {
    expandedEra.value = null
    eraData.value = null
    return
  }

  expandedEra.value = index
  loadingEra.value = true

  try {
    eraData.value = await getEra(props.artist.slug, index)
  } catch (e) {
    console.error('Failed to load era:', e)
    eraData.value = null
  } finally {
    loadingEra.value = false
  }
}
</script>

<template>
  <div class="artist-view">
    <div class="artist-header">
      <h2 class="artist-name">{{ artist.name }}</h2>
      <div class="artist-meta">
        {{ artist.eras?.length || 0 }} eras ·
        {{ artist.total_songs }} songs ·
        {{ artist.total_versions }} versions
      </div>
    </div>

    <div class="eras-list">
      <div v-for="(era, index) in eras" :key="index" class="era-block">
        <EraCard
          :era="era"
          :expanded="expandedEra === index"
          @click="toggleEra(index)"
        />

        <!-- Expanded songs panel -->
        <Transition name="slide">
          <div v-if="expandedEra === index" class="era-songs-panel">
            <div v-if="loadingEra" class="loading-songs">
              <div class="spinner-sm"></div>
              <span>Loading songs...</span>
            </div>
            <SongList
              v-else-if="eraData"
              :songs="eraData.songs || []"
              :artist-name="artist.name"
              :era-name="era.name"
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
  margin-bottom: 28px;
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

.eras-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.era-block {
  /* Container for card + expanded panel */
}

.era-songs-panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-top: none;
  border-radius: 0 0 var(--radius-md) var(--radius-md);
  padding: 16px;
  overflow: hidden;
}

.loading-songs {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  padding: 12px 0;
  font-size: 13px;
}

.spinner-sm {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Transition */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.25s ease;
}
.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.slide-enter-to,
.slide-leave-from {
  opacity: 1;
  max-height: 2000px;
}

@media (max-width: 640px) {
  .artist-view { padding: 16px 12px; }
  .artist-name { font-size: 22px; }
}
</style>
