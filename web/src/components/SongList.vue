<script setup lang="ts">
import { ref, computed } from 'vue'
import SongRow from './SongRow.vue'

const props = defineProps({
  songs: Array,
  sections: Array,
  artistName: String,
  eraName: String,
  eraArt: String,
})

const expandedSong = ref(null)

function toggleSong(index) {
  const prev = expandedSong.value
  expandedSong.value = prev === index ? null : index
}

/** Build a flat list of { type: 'group' | 'section' | 'song', ... } items for rendering */
const displayItems = computed(() => {
  // If sections are provided and have named sections, render with dividers
  if (props.sections?.length) {
    const hasNamedSections = props.sections.some(s => s.name && s.name.trim())
    if (hasNamedSections) {
      const items = []
      let songIdx = 0
      let prevGroup = undefined
      for (const section of props.sections) {
        // Emit a group header when the group changes (null → value or value → value)
        if (section.group !== prevGroup) {
          if (section.group) {
            items.push({ type: 'group', name: section.group, key: 'grp-' + section.group })
          }
          prevGroup = section.group
        }
        if (section.name && section.name.trim()) {
          items.push({ type: 'section', name: section.name, key: `sec-${section.group ?? ''}-${section.name}` })
        }
        for (const song of (section.songs || [])) {
          items.push({ type: 'song', song, index: songIdx, key: song.base_name + songIdx })
          songIdx++
        }
      }
      return items
    }
  }
  // Fallback: flat song list
  const songs = props.songs || (props.sections || []).flatMap(s => s.songs || [])
  return songs.map((song, i) => ({ type: 'song', song, index: i, key: song.base_name + i }))
})

const hasSongs = computed(() => displayItems.value.some(i => i.type === 'song'))
</script>

<template>
  <div class="song-list" role="list" :aria-label="eraName ? eraName + ' songs' : 'Song list'">
    <div v-if="!hasSongs" class="no-songs">No songs found</div>

    <!-- Direct rendering -->
    <template v-else>
      <template v-for="item in displayItems" :key="item.key">
        <div v-if="item.type === 'group'" class="group-divider">
          <span class="group-name">{{ item.name }}</span>
        </div>
        <div v-else-if="item.type === 'section'" class="section-divider">
          <span class="section-name">{{ item.name }}</span>
        </div>
        <SongRow
          v-else
          :song="item.song"
          :expanded="expandedSong === item.index"
          :artist-name="artistName"
          :era-name="eraName"
          :era-art="eraArt"
          @toggle="toggleSong(item.index)"
        />
      </template>
    </template>
  </div>
</template>

<style scoped>
.song-list {
  display: flex;
  flex-direction: column;
}

.no-songs {
  color: var(--text-dim);
  font-size: 13px;
  padding: 12px 0;
  text-align: center;
}

.group-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 8px 4px;
  margin-top: 4px;
}

.group-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: rgba(255, 255, 255, 0.15);
}

.group-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  white-space: nowrap;
  letter-spacing: 0.2px;
}

.section-divider {
  position: sticky;
  top: var(--sticky-era-height, 50px);
  z-index: 8;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 8px 4px 20px;
  margin-top: 4px;
  background: var(--bg-secondary);
}

@media (min-width: 768px) {
  .section-divider {
    top: var(--sticky-era-height, 62px);
  }
}

.section-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: rgba(255, 255, 255, 0.07);
}

.section-name {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--accent-color);
  white-space: nowrap;
  opacity: 0.8;
}
</style>
