<script setup>
import { computed, ref } from 'vue'
import VersionRow from './VersionRow.vue'
import ContextMenu from './ContextMenu.vue'
import SongDescriptionModal from './SongDescriptionModal.vue'
import { playTrack, isStreamable, playerState } from '../composables/usePlayer.js'
import { effectiveBadge, availabilityClass, BADGE_MAP } from '../composables/useUtils.js'

const props = defineProps({
  song: Object,
  expanded: Boolean,
  artistName: String,
  eraName: String,
  eraArt: String,
})

const emit = defineEmits(['toggle'])

const hasMultipleVersions = computed(() => props.song.versions?.length > 1)
const firstVersion = computed(() => props.song.versions?.[0])

const canStream = computed(() => {
  return props.song.versions?.some(v => isStreamable(v)) ?? false
})

const isCurrentSong = computed(() => {
  return props.song.versions?.some(v => v === playerState.track) ?? false
})

const badgeEmoji = computed(() => {
  const b = props.song.badge
  if (!b) return null
  return BADGE_MAP[b] || null
})

const badge = computed(() => {
  if (!firstVersion.value || hasMultipleVersions.value) return null
  return effectiveBadge(firstVersion.value.quality, firstVersion.value.available_length)
})

const availBadge = computed(() => {
  if (!firstVersion.value || hasMultipleVersions.value) return null
  const avail = firstVersion.value.available_length
  if (!avail) return null
  const al = avail.toLowerCase().trim()
  if (al === 'n/a' || al === 'not available') return null
  // Show availability alongside quality if both are meaningful
  const q = (firstVersion.value.quality || '').toLowerCase().trim()
  if (q && q !== 'not available' && q !== 'n/a') {
    // Quality badge is already shown — show availability only if it adds info
    if (['full', 'partial', 'snippet', 'confirmed', 'unavailable'].includes(al)) {
      return { text: avail, cssClass: availabilityClass(avail) }
    }
  }
  return null
})

// A single-version song with no streamable links — open description instead of play
const isConfirmedOnly = computed(() => {
  if (hasMultipleVersions.value || !firstVersion.value) return false
  return !isStreamable(firstVersion.value)
})

// Context menu state
const contextMenu = ref(null)

// Description modal state
const showDescription = ref(false)

function handleClick() {
  if (hasMultipleVersions.value) {
    emit('toggle')
  } else if (isConfirmedOnly.value) {
    showDescription.value = true
  } else if (firstVersion.value) {
    playTrack(firstVersion.value, props.artistName, props.eraName, props.eraArt)
  }
}

function handleContextMenu(e) {
  e.preventDefault()
  contextMenu.value = {
    x: e.clientX,
    y: e.clientY,
    song: props.song,
    version: firstVersion.value,
  }
}

function closeContextMenu() {
  contextMenu.value = null
}

function openDescription() {
  showDescription.value = true
}
</script>

<template>
  <div class="song-row-wrapper">
    <button
      class="song-row"
      :class="{ expanded, playing: isCurrentSong }"
      @click="handleClick"
      @contextmenu="handleContextMenu"
    >
      <div class="song-play-icon" :class="{ streamable: canStream || isConfirmedOnly }">
        <svg v-if="isCurrentSong && playerState.isPlaying" viewBox="0 0 16 16" width="14" height="14" class="eq-icon">
          <rect class="eq-bar eq-1" x="1" y="6" width="3" height="10" rx="1" fill="currentColor"/>
          <rect class="eq-bar eq-2" x="6" y="3" width="3" height="13" rx="1" fill="currentColor"/>
          <rect class="eq-bar eq-3" x="11" y="5" width="3" height="11" rx="1" fill="currentColor"/>
        </svg>
        <svg v-else-if="isConfirmedOnly" viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8zm6.5-.25A.75.75 0 0 1 7.25 7h1a.75.75 0 0 1 .75.75v2.75h.25a.75.75 0 0 1 0 1.5h-2a.75.75 0 0 1 0-1.5h.25v-2h-.25a.75.75 0 0 1-.75-.75zM8 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/>
        </svg>
        <svg v-else-if="!hasMultipleVersions" viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M4 2l12 6-12 6z"/>
        </svg>
        <svg v-else viewBox="0 0 16 16" width="14" height="14" :class="{ rotated: expanded }">
          <path fill="currentColor" d="M4.427 7.427l3.396 3.396a.25.25 0 0 0 .354 0l3.396-3.396A.25.25 0 0 0 11.396 7H4.604a.25.25 0 0 0-.177.427z"/>
        </svg>
      </div>

      <div class="song-content">
        <!-- Title line -->
        <div class="song-title-line">
          <span v-if="badgeEmoji" class="badge-emoji">{{ badgeEmoji }}</span>
          <span class="song-title">{{ song.base_name }}</span>
          <span
            v-if="!hasMultipleVersions && badge"
            class="quality-badge"
            :class="badge.cssClass"
          >{{ badge.text }}</span>
          <span
            v-if="!hasMultipleVersions && availBadge"
            class="avail-pill"
            :class="availBadge.cssClass"
          >{{ availBadge.text }}</span>
          <span v-if="hasMultipleVersions" class="version-count">
            {{ song.versions.length }} versions
          </span>
        </div>

        <!-- Credits lines (multi-line, stacked) -->
        <template v-if="!hasMultipleVersions && firstVersion">
          <div class="song-credits">
            <span v-if="firstVersion.collaboration" class="credit-line">(with {{ firstVersion.collaboration }})</span>
            <span v-if="firstVersion.featuring" class="credit-line"> (feat. {{ firstVersion.featuring }})</span>
            <span v-if="firstVersion.producers" class="credit-line prod"> (prod. {{ firstVersion.producers }})</span>
            <span v-if="firstVersion.refs" class="credit-line ref"> (ref. {{ firstVersion.refs }})</span>
          </div>
          <div v-if="firstVersion.alt_titles?.length" class="song-alt-titles">
            <span v-for="(alt, i) in firstVersion.alt_titles" :key="i" class="alt-title">{{ alt }}</span>
          </div>
        </template>
      </div>

      <!-- Right side: duration -->
      <div class="song-right">
        <span
          v-if="!hasMultipleVersions && firstVersion?.track_length"
          class="track-length"
        >
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
          :era-art="eraArt"
        />
      </div>
    </Transition>

    <!-- Context menu -->
    <ContextMenu
      v-if="contextMenu"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :song="contextMenu.song"
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
      :song="song"
      :version="firstVersion"
      :era-art="eraArt"
      :era-name="eraName"
      :artist-name="artistName"
      @close="showDescription = false"
    />
  </div>
</template>

<style scoped>
.song-row-wrapper {
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.song-row-wrapper:last-child {
  border-bottom: none;
}

.song-row {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 8px;
  border-radius: var(--radius-sm);
  transition: background 0.1s;
}

.song-row:hover {
  background: rgba(255, 255, 255, 0.03);
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
  margin-top: 2px;
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

/* ── Song content (multi-line) ── */
.song-content {
  flex: 1;
  min-width: 0;
}

.song-title-line {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.4;
}

.song-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  margin-left: 4px;
}

.song-credits {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
  opacity: 0.7;
  text-align: left;
}

.credit-line {
  /* inline so they wrap naturally */
}

.credit-line.prod {
  color: var(--text-dim);
}

.credit-line.ref {
  color: var(--text-dim);
  font-style: italic;
}

.song-alt-titles {
  font-size: 11px;
  color: var(--text-secondary);
  font-style: italic;
  opacity: 0.65;
  line-height: 1.5;
  margin-top: 2px;
  text-align: left;
}

.alt-title {
  display: inline-block;
  margin-right: 6px;
}

.alt-title::before { content: '('; }
.alt-title::after  { content: ')'; }

/* ── Right side ── */
.song-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  margin-top: 2px;
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

/* Availability badges */
.a-full { background: rgba(78,205,196,0.15); color: var(--badge-og); }
.a-partial { background: rgba(240,136,62,0.15); color: var(--badge-lq); }
.a-snippet { background: rgba(210,168,255,0.15); color: var(--badge-recording); }
.a-confirmed { background: rgba(88,166,255,0.15); color: var(--badge-hq); }
.a-unavailable { background: rgba(82,90,101,0.15); color: var(--badge-na); }
.a-na { background: rgba(82,90,101,0.15); color: var(--badge-na); }

.avail-pill {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 6px;
  border-radius: 3px;
  white-space: nowrap;
}

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
  .song-row { padding: 8px 4px; gap: 8px; }
  .song-title-line { font-size: 13px; }
  .quality-badge, .avail-pill { font-size: 9px; padding: 1px 4px; }
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
