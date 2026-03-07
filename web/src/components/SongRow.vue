<script setup>
import { computed, ref } from 'vue'
import VersionRow from './VersionRow.vue'
import { Badge } from '@/components/ui/badge'
import { playTrack, isStreamable, playerState, isTrackMatch } from '../composables/usePlayer'
import { effectiveBadge, getAvailBadge, BADGE_MAP } from '../composables/useUtils'
import { useSharedOverlays } from '../composables/useSharedOverlays'

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
  return props.song.versions?.some(v => isTrackMatch(v)) ?? false
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

/** Collect all unique alt titles across all versions for multi-version songs */
const allAltTitles = computed(() => {
  if (!hasMultipleVersions.value) return []
  const seen = new Set()
  const titles = []
  for (const v of (props.song.versions || [])) {
    for (const alt of (v.alt_titles || [])) {
      const key = alt.toLowerCase().trim()
      if (!seen.has(key)) {
        seen.add(key)
        titles.push(alt)
      }
    }
  }
  return titles
})

const availBadge = computed(() => {
  if (!firstVersion.value || hasMultipleVersions.value) return null
  return getAvailBadge(firstVersion.value.quality, firstVersion.value.available_length)
})

// A single-version song with no streamable links — open description instead of play
const isConfirmedOnly = computed(() => {
  if (hasMultipleVersions.value || !firstVersion.value) return false
  return !isStreamable(firstVersion.value)
})

// Shared overlays (single ContextMenu + Modal at ArtistView level)
const { showContextMenu, showDescription: showDescriptionModal } = useSharedOverlays()

function handleClick() {
  if (hasMultipleVersions.value) {
    emit('toggle')
  } else if (isConfirmedOnly.value) {
    showDescriptionModal({
      song: props.song,
      version: firstVersion.value,
      artistName: props.artistName,
      eraName: props.eraName,
      eraArt: props.eraArt,
    })
  } else if (firstVersion.value) {
    playTrack(firstVersion.value, props.artistName, props.eraName, props.eraArt)
  }
}

function handleContextMenu(e) {
  e.preventDefault()
  showContextMenu({
    x: e.clientX,
    y: e.clientY,
    song: props.song,
    version: firstVersion.value,
    artistName: props.artistName,
    eraName: props.eraName,
    eraArt: props.eraArt,
  })
}
</script>

<template>
  <div class="song-row-wrapper">
    <button
      class="song-row"
      :class="{ expanded, playing: isCurrentSong, 'confirmed-only': isConfirmedOnly && !hasMultipleVersions }"
      @click="handleClick"
      @contextmenu="handleContextMenu"
    >
      <div class="song-content">
        <!-- Title line -->
        <div class="song-title-line">
          <span class="badge-slot">{{ badgeEmoji || '' }}</span>
          <span class="song-title">{{ song.base_name }}</span>
          <Badge
            v-if="!hasMultipleVersions && badge"
            :variant="badge.variant"
          >{{ badge.text }}</Badge>
          <Badge
            v-if="!hasMultipleVersions && availBadge"
            :variant="availBadge.variant"
          >{{ availBadge.text }}</Badge>
          <!-- Expand chevron for multi-version -->
          <svg v-if="hasMultipleVersions" viewBox="0 0 16 16" width="12" height="12" class="expand-chevron" :class="{ rotated: expanded }">
            <path fill="currentColor" d="M4.427 7.427l3.396 3.396a.25.25 0 0 0 .354 0l3.396-3.396A.25.25 0 0 0 11.396 7H4.604a.25.25 0 0 0-.177.427z"/>
          </svg>
        </div>

        <!-- Alt titles for multi-version songs (shown on parent, not per-version) -->
        <div v-if="hasMultipleVersions && allAltTitles.length" class="song-alt-titles">
          <span v-for="(alt, i) in allAltTitles" :key="i" class="alt-title"><span class="alt-title-inner">{{ alt }}</span></span>
        </div>

        <!-- Credits lines -->
        <template v-if="!hasMultipleVersions && firstVersion">
          <div v-if="firstVersion.collaboration || firstVersion.featuring || firstVersion.producers || firstVersion.refs" class="song-credits">
            <span v-if="firstVersion.collaboration" class="credit-item credit-collab">with {{ firstVersion.collaboration }}</span>
            <span v-if="firstVersion.featuring" class="credit-item credit-feat">feat. {{ firstVersion.featuring }}</span>
            <span v-if="firstVersion.producers" class="credit-item credit-prod">prod. {{ firstVersion.producers }}</span>
            <span v-if="firstVersion.refs" class="credit-item credit-ref">ref. {{ firstVersion.refs }}</span>
          </div>
          <div v-if="firstVersion.alt_titles?.length" class="song-alt-titles">
            <span v-for="(alt, i) in firstVersion.alt_titles" :key="i" class="alt-title">{{ alt }}</span>
          </div>
        </template>
      </div>

      <!-- Right side: duration + confirmed-only indicator -->
      <div class="song-right">
        <span
          v-if="!hasMultipleVersions && firstVersion?.track_length"
          class="track-length"
        >
          {{ firstVersion.track_length }}
        </span>
        <!-- Info icon: clicking will open description, not play -->
        <svg
          v-if="isConfirmedOnly && !hasMultipleVersions"
          class="confirmed-icon"
          viewBox="0 0 16 16"
          width="13"
          height="13"
          aria-label="Confirmed — no file available"
        >
          <path fill="currentColor" d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM6.5 7.75v3.5a.75.75 0 0 0 1.5 0v-3.5a.75.75 0 0 0-1.5 0ZM8 6a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"/>
        </svg>
      </div>
    </button>

    <!-- Accordion: version list -->
    <Transition name="versions">
      <div v-if="expanded && hasMultipleVersions" class="versions-panel">
        <div class="versions-panel-inner">
          <VersionRow
            v-for="(v, i) in song.versions"
            :key="i"
            :version="v"
            :artist-name="artistName"
            :era-name="eraName"
            :era-art="eraArt"
            :hide-alt-titles="true"
          />
        </div>
      </div>
    </Transition>
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
  gap: 0;
  padding: 12px 10px;
  min-height: 44px;
  border-radius: var(--radius-md);
  transition: all 0.2s ease;
  border: 1px solid transparent;
  -webkit-tap-highlight-color: transparent;
}

.song-row:hover {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.05);
  border-left-color: hsl(var(--primary) / 0.4);
  border-left-width: 2px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transform: translateX(2px);
}

.song-row.playing {
  background: rgba(88, 166, 255, 0.05);
  border-color: rgba(88, 166, 255, 0.1);
}

.song-row.confirmed-only {
  cursor: default;
}

.song-row.confirmed-only:hover {
  border-left-color: transparent;
  border-left-width: 1px;
  transform: none;
}

.confirmed-icon {
  color: var(--text-dim);
  flex-shrink: 0;
  opacity: 0.6;
}

/* Equalizer animation for playing state */
.song-row.playing .badge-slot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1.5px;
}

.song-row.playing .badge-slot::before,
.song-row.playing .badge-slot::after {
  content: '';
  display: block;
  width: 2.5px;
  border-radius: 1px;
  background: hsl(var(--primary));
  animation: eq-bar 0.8s ease-in-out infinite alternate;
}

.song-row.playing .badge-slot::before {
  height: 10px;
  animation-delay: 0s;
}

.song-row.playing .badge-slot::after {
  height: 6px;
  animation-delay: 0.3s;
}

.expand-chevron {
  flex-shrink: 0;
  color: var(--text-dim);
  margin-left: 2px;
  transition: transform 0.2s ease;
}

.expand-chevron.rotated {
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
  min-width: 0;
}

.badge-slot {
  width: 20px;
  min-width: 20px;
  font-size: 14px;
  flex-shrink: 0;
  text-align: center;
}

.song-credits {
  font-size: 11px;
  line-height: 1.5;
  text-align: left;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.credit-item {
  white-space: nowrap;
  background: rgba(255, 255, 255, 0.04);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.credit-collab {
  color: var(--text-primary);
}

.credit-feat {
  color: var(--text-primary);
}

.credit-prod {
  color: var(--text-secondary);
}

.credit-ref {
  color: var(--text-dim);
  font-style: italic;
}

.song-alt-titles {
  font-size: 11.5px;
  color: rgba(255, 255, 255, 0.6);
  line-height: 1.5;
  margin-top: 4px;
  text-align: left;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.alt-title {
  display: inline-flex;
  align-items: center;
}

.alt-title::before {
  content: '\B7';
  margin-right: 0;
  color: var(--text-dim);
}

.alt-title-inner,
.alt-title {
  /* no wrapping pseudo-parens, just comma-separated */
}

/* ── Right side ── */
.song-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  margin-top: 2px;
}

.track-length {
  color: var(--text-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* Versions accordion */
.versions-panel-inner {
  padding: 0 0 4px 16px;
  overflow: hidden;
  min-height: 0;
}

/* Accordion transition using grid technique */
.versions-panel {
  display: grid;
  grid-template-rows: 1fr;
}

.versions-enter-active,
.versions-leave-active {
  transition: grid-template-rows 0.25s ease, opacity 0.2s ease;
}
.versions-enter-from,
.versions-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
}
.versions-enter-to,
.versions-leave-from {
  grid-template-rows: 1fr;
  opacity: 1;
}

@media (max-width: 640px) {
  .song-row { padding: 8px 4px; }
  .song-title-line { font-size: 13px; }
  .versions-panel { padding-left: 12px; }
}


</style>
