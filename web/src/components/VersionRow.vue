<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { playTrack, isStreamable, playerState, isTrackMatch, addToQueue } from '../composables/usePlayer'
import { effectiveBadge, getAvailBadge, BADGE_MAP, coloredBadgeStyle } from '../composables/useUtils'
import { useSharedOverlays } from '../composables/useSharedOverlays'

const props = defineProps({
  version: Object,
  artistName: String,
  eraName: String,
  eraArt: String,
  hideAltTitles: Boolean,
})

const canStream = computed(() => isStreamable(props.version))

const isCurrentTrack = computed(() => isTrackMatch(props.version))

// Shared overlays (single ContextMenu + Modal at ArtistView level)
const { showContextMenu, showDescription: showDescriptionModal } = useSharedOverlays()

function handlePlay() {
  if (!canStream.value) {
    showDescriptionModal({
      version: props.version,
      artistName: props.artistName,
      eraName: props.eraName,
      eraArt: props.eraArt,
    })
    return
  }
  playTrack(props.version, props.artistName, props.eraName, props.eraArt)
}

function handleContextMenu(e) {
  e.preventDefault()
  showContextMenu({
    x: e.clientX,
    y: e.clientY,
    version: props.version,
    artistName: props.artistName,
    eraName: props.eraName,
    eraArt: props.eraArt,
  })
}

function handleAddToQueue(e) {
  e.stopPropagation()
  addToQueue(props.version, props.artistName, props.eraName, props.eraArt)
}

const badge = computed(() => {
  return effectiveBadge(props.version.quality, props.version.available_length)
})

const availBadge = computed(() => {
  return getAvailBadge(props.version.quality, props.version.available_length)
})

const badgeEmoji = computed(() => {
  const b = props.version.badge
  if (!b) return null
  return BADGE_MAP[b] || null
})

const qualityStyle = computed(() => coloredBadgeStyle(props.version.quality_color))
const availStyle = computed(() => coloredBadgeStyle(props.version.available_length_color))
</script>

<template>
  <button
    class="version-row"
    :class="{ playing: isCurrentTrack }"
    @click="handlePlay"
    @contextmenu="handleContextMenu"
  >
    <div class="v-content">
      <!-- Title line -->
      <div class="v-title-line">
        <span class="v-badge-slot">{{ badgeEmoji || '' }}</span>
        <span class="v-title">{{ version.name }}</span>
        <span v-if="version.version_tag" class="v-tag">[{{ version.version_tag }}]</span>
        <Badge v-if="badge" :variant="qualityStyle ? undefined : badge.variant" :style="qualityStyle">{{ badge.text }}</Badge>
        <Badge v-if="availBadge" :variant="availStyle ? undefined : availBadge.variant" :style="availStyle">{{ availBadge.text }}</Badge>
      </div>

      <!-- Credits lines -->
      <div v-if="version.collaboration || version.featuring || version.producers || version.refs" class="v-credits">
        <span v-if="version.collaboration" class="v-credit v-credit-collab">with {{ version.collaboration }}</span>
        <span v-if="version.featuring" class="v-credit v-credit-feat">feat. {{ version.featuring }}</span>
        <span v-if="version.producers" class="v-credit v-credit-prod">prod. {{ version.producers }}</span>
        <span v-if="version.refs" class="v-credit v-credit-ref">ref. {{ version.refs }}</span>
      </div>

      <div v-if="!hideAltTitles && version.alt_titles?.length" class="v-alt-titles">
        <span v-for="(alt, i) in version.alt_titles" :key="i" class="v-alt-item">{{ alt }}</span>
      </div>
    </div>

    <div class="v-right">
      <span v-if="version.track_length" class="v-length">
        {{ version.track_length }}
      </span>
      <!-- Mobile-only queue button -->
      <button
        v-if="canStream"
        class="mobile-queue-btn"
        aria-label="Add to queue"
        @click="handleAddToQueue"
      >
        <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
          <path fill="currentColor" d="M0 2.75A.75.75 0 0 1 .75 2h12.5a.75.75 0 0 1 0 1.5H.75A.75.75 0 0 1 0 2.75zm0 5A.75.75 0 0 1 .75 7h7.5a.75.75 0 0 1 0 1.5H.75A.75.75 0 0 1 0 7.75zm0 5a.75.75 0 0 1 .75-.75h7.5a.75.75 0 0 1 0 1.5H.75a.75.75 0 0 1-.75-.75zM14 7a1 1 0 0 1 1 1v1h1a1 1 0 0 1 0 2h-1v1a1 1 0 0 1-2 0v-1h-1a1 1 0 0 1 0-2h1V8a1 1 0 0 1 1-1z"/>
        </svg>
      </button>
    </div>
  </button>
</template>

<style scoped>
.version-row {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 0;
  padding: 8px 8px;
  min-height: 44px;
  border-radius: var(--radius-md);
  transition: all 0.2s ease;
  font-size: 13px;
  border: 1px solid transparent;
  -webkit-tap-highlight-color: transparent;
}

.version-row:hover {
  background: rgba(255, 255, 255, 0.02);
  border-color: rgba(255, 255, 255, 0.03);
  border-left-color: hsl(var(--primary) / 0.3);
  border-left-width: 2px;
  transform: translateX(2px);
}

.version-row.playing {
  background: rgba(88, 166, 255, 0.05);
  border-color: rgba(88, 166, 255, 0.1);
}

/* Equalizer animation for playing state — @keyframes eq-bar defined globally in style.css */
.version-row.playing .v-badge-slot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1.5px;
}

.version-row.playing .v-badge-slot::before,
.version-row.playing .v-badge-slot::after {
  content: '';
  display: block;
  width: 2px;
  border-radius: 1px;
  background: hsl(var(--primary));
  animation: eq-bar 0.8s ease-in-out infinite alternate;
}

.version-row.playing .v-badge-slot::before {
  height: 8px;
  animation-delay: 0s;
}

.version-row.playing .v-badge-slot::after {
  height: 5px;
  animation-delay: 0.3s;
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

.v-badge-slot {
  width: 18px;
  min-width: 18px;
  font-size: 12px;
  flex-shrink: 0;
  text-align: center;
}

.v-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.v-tag {
  color: var(--text-dim);
  font-size: 11px;
  flex-shrink: 0;
}

.v-credits {
  font-size: 11px;
  line-height: 1.4;
  text-align: left;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.v-credit {
  white-space: nowrap;
  background: rgba(255, 255, 255, 0.04);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.v-credit-collab {
  color: var(--text-primary);
}

.v-credit-feat {
  color: var(--text-primary);
}

.v-credit-prod {
  color: var(--text-secondary);
}

.v-credit-ref {
  color: var(--text-dim);
  font-style: italic;
}

.v-alt-titles {
  font-size: 10.5px;
  color: rgba(255, 255, 255, 0.6);
  line-height: 1.4;
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.v-alt-item {
  display: inline-flex;
  align-items: center;
}

.v-alt-item::before {
  content: '\B7';
  margin-right: 0;
  color: var(--text-dim);
}

.v-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-top: 1px;
}

.v-length {
  color: var(--text-secondary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.mobile-queue-btn {
  display: none;
  align-items: center;
  justify-content: center;
  padding: 5px;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 5px;
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  flex-shrink: 0;
  -webkit-tap-highlight-color: transparent;
}

.mobile-queue-btn:active {
  background: rgba(255, 255, 255, 0.15);
  color: rgba(255, 255, 255, 0.9);
}

@media (hover: none) and (pointer: coarse) {
  .mobile-queue-btn {
    display: flex;
  }
}

@media (max-width: 640px) {
  .version-row { font-size: 11px; gap: 6px; }
  /* Prevent long quality badges from squeezing the title to zero width */
  .v-title { min-width: 60px; }
  .v-title-line :deep(.inline-flex) { flex-shrink: 1; }
}
</style>
