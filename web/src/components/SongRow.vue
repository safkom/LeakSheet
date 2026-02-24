<script setup>
import { computed } from 'vue'
import VersionRow from './VersionRow.vue'
import { playTrack, isStreamable, playerState } from '../composables/usePlayer.js'

const props = defineProps({
  song: Object,
  expanded: Boolean,
  artistName: String,
  eraName: String,
})

const emit = defineEmits(['toggle'])

const hasMultipleVersions = computed(() => props.song.versions?.length > 1)
const firstVersion = computed(() => props.song.versions?.[0])

const canStream = computed(() => {
  // Any version streamable → song is streamable
  return props.song.versions?.some(v => isStreamable(v)) ?? false
})

const isCurrentSong = computed(() => {
  return props.song.versions?.some(v => v === playerState.track) ?? false
})

const badgeEmoji = computed(() => {
  const b = props.song.badge
  if (!b) return null
  const map = { best: '⭐', special: '✨', worst: '🗑️', grail: '🏆', wanted: '🏅' }
  return map[b] || null
})

function handleClick() {
  if (hasMultipleVersions.value) {
    emit('toggle')
  } else if (firstVersion.value) {
    playTrack(firstVersion.value, props.artistName, props.eraName)
  }
}

function qualityClass(q) {
  if (!q) return 'q-na'
  const l = q.toLowerCase()
  if (l.includes('og') || l.includes('lossless')) return 'q-og'
  if (l.includes('cd')) return 'q-cd'
  if (l.includes('high')) return 'q-hq'
  if (l.includes('low')) return 'q-lq'
  if (l.includes('recording')) return 'q-rec'
  return 'q-na'
}
</script>

<template>
  <div class="song-row-wrapper">
    <button class="song-row" :class="{ expanded, playing: isCurrentSong }" @click="handleClick">
      <div class="song-play-icon" :class="{ streamable: canStream }">
        <svg v-if="isCurrentSong && playerState.isPlaying" viewBox="0 0 16 16" width="14" height="14" class="eq-icon">
          <rect class="eq-bar eq-1" x="1" y="6" width="3" height="10" rx="1" fill="currentColor"/>
          <rect class="eq-bar eq-2" x="6" y="3" width="3" height="13" rx="1" fill="currentColor"/>
          <rect class="eq-bar eq-3" x="11" y="5" width="3" height="11" rx="1" fill="currentColor"/>
        </svg>
        <svg v-else-if="!hasMultipleVersions" viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M4 2l12 6-12 6z"/>
        </svg>
        <svg v-else viewBox="0 0 16 16" width="14" height="14" :class="{ rotated: expanded }">
          <path fill="currentColor" d="M4.427 7.427l3.396 3.396a.25.25 0 0 0 .354 0l3.396-3.396A.25.25 0 0 0 11.396 7H4.604a.25.25 0 0 0-.177.427z"/>
        </svg>
      </div>

      <div v-if="!hasMultipleVersions && firstVersion" class="song-meta-left">
        <span v-if="firstVersion.quality" class="quality-badge" :class="qualityClass(firstVersion.quality)">
          {{ firstVersion.quality }}
        </span>
      </div>

      <div class="song-name">
        <span v-if="badgeEmoji" class="badge-emoji">{{ badgeEmoji }}</span>
        <span class="song-title">{{ song.base_name }}</span>
        <template v-if="!hasMultipleVersions">
          <span v-if="firstVersion?.collaboration" class="song-credit">(with {{ firstVersion.collaboration }})</span>
          <span v-if="firstVersion?.featuring" class="song-credit">(feat. {{ firstVersion.featuring }})</span>
          <span v-if="firstVersion?.producers" class="song-credit prod">(prod. {{ firstVersion.producers }})</span>
          <span v-if="firstVersion?.refs" class="song-credit ref">(ref. {{ firstVersion.refs }})</span>
          <span v-if="firstVersion?.alt_titles?.length" class="song-alt">
            <span v-for="(alt, i) in firstVersion.alt_titles" :key="i">({{ alt }})</span>
          </span>
        </template>
        <span v-if="hasMultipleVersions" class="version-count">
          {{ song.versions.length }} versions
        </span>
      </div>

      <div v-if="!hasMultipleVersions && firstVersion" class="song-meta">
        <span v-if="firstVersion.track_length" class="track-length">
          {{ firstVersion.track_length }}
        </span>
      </div>
    </button>

    <!-- Accordion: version list -->
    <Transition name="versions">
      <div v-if="expanded && hasMultipleVersions" class="versions-panel">
        <VersionRow
          v-for="(v, i) in song.versions"
          :key="i"
          :version="v"
          :artist-name="artistName"
          :era-name="eraName"
        />
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.song-row-wrapper {
  border-bottom: 1px solid var(--border);
}

.song-row-wrapper:last-child {
  border-bottom: none;
}

.song-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 8px;
  border-radius: var(--radius-sm);
  transition: background 0.1s;
}

.song-row:hover {
  background: var(--bg-card);
}

.song-play-icon {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  transition: color 0.1s;
  opacity: 0.35;
}

.song-play-icon.streamable {
  opacity: 1;
}

.song-row:hover .song-play-icon {
  color: var(--accent);
  opacity: 1;
}

.song-row.playing .song-play-icon {
  color: var(--accent);
  opacity: 1;
}

.song-row.playing {
  background: rgba(88,166,255,0.05);
}

.song-play-icon svg {
  transition: transform 0.2s ease;
}

.song-play-icon .rotated {
  transform: rotate(180deg);
}

.song-meta-left {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  min-width: 90px;
}

.song-name {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  align-items: center;
  gap: 4px;
}

.song-title {
  flex-shrink: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}

.song-credit {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 400;
  flex-shrink: 0;
  opacity: 0.7;
}

.song-credit.prod {
  color: var(--text-dim);
}

.song-credit.ref {
  color: var(--text-dim);
  font-style: italic;
}

.song-alt {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 400;
  font-style: italic;
  flex-shrink: 0;
  opacity: 0.5;
}

.badge-emoji {
  font-size: 14px;
  flex-shrink: 0;
}

.version-count {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 400;
  flex-shrink: 0;
}

.song-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.quality-badge {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 6px;
  border-radius: 3px;
  white-space: nowrap;
}

.q-og { background: rgba(78,205,196,0.15); color: var(--badge-og); }
.q-hq { background: rgba(88,166,255,0.15); color: var(--badge-hq); }
.q-cd { background: rgba(163,113,247,0.15); color: var(--badge-cd); }
.q-lq { background: rgba(240,136,62,0.15); color: var(--badge-lq); }
.q-rec { background: rgba(210,168,255,0.15); color: var(--badge-recording); }
.q-na { background: rgba(82,90,101,0.15); color: var(--badge-na); }

.track-length {
  color: var(--text-dim);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* Versions accordion */
.versions-panel {
  padding: 0 0 4px 34px;
  overflow: hidden;
}

.versions-enter-active,
.versions-leave-active {
  transition: all 0.2s ease;
}
.versions-enter-from,
.versions-leave-to {
  opacity: 0;
  max-height: 0;
}
.versions-enter-to,
.versions-leave-from {
  opacity: 1;
  max-height: 1000px;
}

@media (max-width: 640px) {
  .song-row { padding: 6px 4px; gap: 8px; }
  .song-name { font-size: 12px; }
  .quality-badge { font-size: 9px; padding: 1px 4px; }
  .versions-panel { padding-left: 24px; }
}

/* Equalizer animation */
.eq-icon { color: var(--accent); }
.eq-bar { transform-origin: bottom; animation: eq 0.8s ease-in-out infinite alternate; }
.eq-1 { animation-delay: 0s; }
.eq-2 { animation-delay: 0.2s; }
.eq-3 { animation-delay: 0.4s; }
@keyframes eq {
  0% { transform: scaleY(0.3); }
  100% { transform: scaleY(1); }
}
</style>
