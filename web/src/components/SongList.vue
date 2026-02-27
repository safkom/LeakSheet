<script setup>
import { ref } from 'vue'
import SongRow from './SongRow.vue'

const props = defineProps({
  songs: Array,
  artistName: String,
  eraName: String,
  eraArt: String,
})

const expandedSong = ref(null)

function toggleSong(index) {
  expandedSong.value = expandedSong.value === index ? null : index
}
</script>

<template>
  <div class="song-list">
    <div v-if="!songs.length" class="no-songs">No songs found</div>
    <SongRow
      v-for="(song, index) in songs"
      :key="song.base_name + index"
      :song="song"
      :expanded="expandedSong === index"
      :artist-name="artistName"
      :era-name="eraName"
      :era-art="eraArt"
      @toggle="toggleSong(index)"
    />
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
</style>
