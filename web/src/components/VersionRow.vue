<script setup>
import { computed, ref } from 'vue'
import ContextMenu from './ContextMenu.vue'
import SongDescriptionModal from './SongDescriptionModal.vue'
import { playTrack, isStreamable, playerState } from '../composables/usePlayer.js'
import { effectiveBadge, availabilityClass, BADGE_MAP } from '../composables/useUtils.js'

const props = defineProps({
  version: Object,
  artistName: String,
  eraName: String,
  eraArt: String,
  hideAltTitles: Boolean,
})

const canStream = computed(() => isStreamable(props.version))

const isCurrentTrack = computed(() => {
  return playerState.track === props.version
})

// Context menu state
const contextMenu = ref(null)
const showDescription = ref(false)

function handlePlay() {
  if (!canStream.value) {
    showDescription.value = true
    return
  }
  playTrack(props.version, props.artistName, props.eraName, props.eraArt)
}

function handleContextMenu(e) {
  e.preventDefault()
  contextMenu.value = {
    x: e.clientX,
    y: e.clientY,
    version: props.version,
  }
}

function closeContextMenu() {
  contextMenu.value = null
}

function openDescription() {
  showDescription.value = true
}

const badge = computed(() => {
  return effectiveBadge(props.version.quality, props.version.available_length)
})

const availBadge = computed(() => {
  const avail = props.version.available_length
  if (!avail) return null
  const al = avail.toLowerCase().trim()
  if (al === 'n/a' || al === 'not available') return null
  const q = (props.version.quality || '').toLowerCase().trim()
  if (q && q !== 'not available' && q !== 'n/a') {
    if (['full', 'partial', 'snippet', 'confirmed', 'unavailable'].includes(al)) {
      return { text: avail, cssClass: availabilityClass(avail) }
    }
  }
  return null
})

const badgeEmoji = computed(() => {
  const b = props.version.badge
  if (!b) return null
  return BADGE_MAP[b] || null
})
</script>

<template>
  <button
    class="version-row"
    :class="{ playing: isCurrentTrack }"
    @click="handlePlay"
    @contextmenu="handleContextMenu"
  >
    <div class="v-play streamable">
      <svg v-if="isCurrentTrack && playerState.isPlaying" viewBox="0 0 16 16" width="12" height="12" class="eq-icon">
        <rect class="eq-bar eq-1" x="1" y="6" width="3" height="10" rx="1" fill="currentColor"/>
        <rect class="eq-bar eq-2" x="6" y="3" width="3" height="13" rx="1" fill="currentColor"/>
        <rect class="eq-bar eq-3" x="11" y="5" width="3" height="11" rx="1" fill="currentColor"/>
      </svg>
      <svg v-else-if="!canStream" viewBox="0 0 16 16" width="12" height="12">
        <path fill="currentColor" d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8zm6.5-.25A.75.75 0 0 1 7.25 7h1a.75.75 0 0 1 .75.75v2.75h.25a.75.75 0 0 1 0 1.5h-2a.75.75 0 0 1 0-1.5h.25v-2h-.25a.75.75 0 0 1-.75-.75zM8 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/>
      </svg>
      <svg v-else viewBox="0 0 16 16" width="12" height="12">
        <path fill="currentColor" d="M4 2l12 6-12 6z"/>
      </svg>
    </div>

    <div class="v-content">
      <!-- Title line -->
      <div class="v-title-line">
        <span v-if="badgeEmoji" class="v-badge">{{ badgeEmoji }}</span>
        <span class="v-title">{{ version.name }}</span>
        <span v-if="version.version_tag" class="v-tag">[{{ version.version_tag }}]</span>
        <span v-if="badge" class="quality-badge" :class="badge.cssClass">{{ badge.text }}</span>
        <span v-if="availBadge" class="avail-pill" :class="availBadge.cssClass">{{ availBadge.text }}</span>
      </div>

      <!-- Credits lines -->
      <div v-if="version.collaboration || version.featuring || version.producers || version.refs" class="v-credits">
        <span v-if="version.collaboration" class="v-credit">(with {{ version.collaboration }})</span>
        <span v-if="version.featuring" class="v-credit"> (feat. {{ version.featuring }})</span>
        <span v-if="version.producers" class="v-credit prod"> (prod. {{ version.producers }})</span>
        <span v-if="version.refs" class="v-credit ref"> (ref. {{ version.refs }})</span>
      </div>

      <div v-if="!hideAltTitles && version.alt_titles?.length" class="v-alt-titles">
        <span v-for="(alt, i) in version.alt_titles" :key="i" class="v-alt-item">{{ alt }}</span>
      </div>
    </div>

    <div class="v-right">
      <span v-if="version.track_length" class="v-length">
        {{ version.track_length }}
      </span>
    </div>
  </button>

  <!-- Context menu -->
  <ContextMenu
    v-if="contextMenu"
    :x="contextMenu.x"
    :y="contextMenu.y"
    :version="contextMenu.version"
    :artist-name="artistName"
    :era-name="eraName"
    :era-art="eraArt"
    @close="closeContextMenu"
    @show-description="openDescription"
  />

  <!-- Description modal -->
  <SongDescriptionModal
    v-if="showDescription"
    :version="version"
    :era-art="eraArt"
    :era-name="eraName"
    :artist-name="artistName"
    @close="showDescription = false"
  />
</template>

<style scoped>
.version-row {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 6px;
  border-radius: var(--radius-sm);
  transition: background 0.1s;
  font-size: 12px;
}

.version-row:hover {
  background: rgba(255, 255, 255, 0.03);
}

.v-play {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  transition: color 0.1s;
  opacity: 0.35;
  margin-top: 1px;
}

.v-play.streamable {
  opacity: 1;
}

.version-row:hover .v-play {
  color: var(--accent);
  opacity: 1;
}

.version-row.playing .v-play {
  color: var(--accent);
  opacity: 1;
}

.version-row.playing {
  background: rgba(88,166,255,0.05);
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

.v-content {
  flex: 1;
  min-width: 0;
}

.v-title-line {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 400;
  color: var(--text-secondary);
  line-height: 1.4;
}

.v-badge {
  font-size: 12px;
  flex-shrink: 0;
}

.v-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.v-tag {
  color: var(--text-dim);
  font-size: 11px;
  flex-shrink: 0;
}

.v-credits {
  font-size: 11px;
  color: var(--text-secondary);
  opacity: 0.6;
  line-height: 1.4;
  text-align: left;
}

.v-credit.prod {
  color: var(--text-dim);
}

.v-credit.ref {
  color: var(--text-dim);
  font-style: italic;
}

.v-alt-titles {
  font-size: 10px;
  color: var(--text-secondary);
  font-style: italic;
  opacity: 0.65;
  line-height: 1.4;
  margin-top: 2px;
}

.v-alt-item {
  display: inline-block;
  margin-right: 4px;
}
.v-alt-item::before { content: '('; }
.v-alt-item::after  { content: ')'; }

.v-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-top: 1px;
}

.quality-badge {
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 1px 5px;
  border-radius: 3px;
  white-space: nowrap;
}

.q-og { background: rgba(78,205,196,0.15); color: var(--badge-og); }
.q-hq { background: rgba(88,166,255,0.15); color: var(--badge-hq); }
.q-cd { background: rgba(163,113,247,0.15); color: var(--badge-cd); }
.q-lq { background: rgba(240,136,62,0.15); color: var(--badge-lq); }
.q-rec { background: rgba(210,168,255,0.15); color: var(--badge-recording); }
.q-na { background: rgba(82,90,101,0.15); color: var(--badge-na); }

.a-full { background: rgba(78,205,196,0.15); color: var(--badge-og); }
.a-partial { background: rgba(240,136,62,0.15); color: var(--badge-lq); }
.a-snippet { background: rgba(210,168,255,0.15); color: var(--badge-recording); }
.a-confirmed { background: rgba(88,166,255,0.15); color: var(--badge-hq); }
.a-unavailable { background: rgba(82,90,101,0.15); color: var(--badge-na); }
.a-na { background: rgba(82,90,101,0.15); color: var(--badge-na); }

.avail-pill {
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 1px 5px;
  border-radius: 3px;
  white-space: nowrap;
}

.v-length {
  color: var(--text-dim);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .version-row { font-size: 11px; gap: 6px; }
  .quality-badge, .avail-pill { font-size: 8px; }
}
</style>
