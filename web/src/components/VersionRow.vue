<script setup lang="ts">
import { computed, type PropType } from 'vue'
import BadgeRow from './BadgeRow.vue'
import CreditTags from './CreditTags.vue'
import { playTrack, isStreamable, playerState, isTrackMatch, addToQueue } from '../composables/usePlayer'
import { BADGE_MAP } from '../composables/useUtils'
import { useSharedOverlays } from '../composables/useSharedOverlays'
import { useSwipeAction } from '../composables/useSwipeAction'
import { useLongPress } from '../composables/useLongPress'
import type { Song, SongVersion } from '../composables/useEraFiltering'

const props = defineProps({
  version: { type: Object as PropType<SongVersion>, required: true },
  /** Parent song — when provided, the heart favourites the whole song (not just this version) */
  parentSong: { type: Object as PropType<Song>, default: null },
  artistName: String,
  artistSlug: String,
  sourceUrl: { type: String as PropType<string | null>, default: null },
  eraName: String,
  eraArt: String,
  hideAltTitles: Boolean,
})

const canStream = computed(() => isStreamable(props.version))

const isCurrentTrack = computed(() => isTrackMatch(props.version))
const isCurrentLoading = computed(() => isCurrentTrack.value && playerState.loading)

// Shared overlays (single ContextMenu + Modal at ArtistView level)
const { showContextMenu, showDescription: showDescriptionModal } = useSharedOverlays()

function handlePlay() {
  if (swipe.isSwiping.value) return
  if (!canStream.value) {
    showDescriptionModal({
      version: props.version,
      artistName: props.artistName,
      artistSlug: props.artistSlug,
      sourceUrl: props.sourceUrl,
      eraName: props.eraName,
      eraArt: props.eraArt,
    })
    return
  }
  navigator.vibrate?.(8)
  playTrack(props.version, props.artistName, props.eraName, props.eraArt)
}

function handleContextMenu(e) {
  e.preventDefault()
  showContextMenu({
    x: e.clientX,
    y: e.clientY,
    song: props.parentSong || undefined,
    version: props.version,
    artistName: props.artistName,
    artistSlug: props.artistSlug,
    sourceUrl: props.sourceUrl,
    eraName: props.eraName,
    eraArt: props.eraArt,
  })
}

function handleMobileMenu(e: MouseEvent) {
  e.stopPropagation()
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  showContextMenu({
    x: rect.left,
    y: rect.bottom + 4,
    song: props.parentSong || undefined,
    version: props.version,
    artistName: props.artistName,
    artistSlug: props.artistSlug,
    sourceUrl: props.sourceUrl,
    eraName: props.eraName,
    eraArt: props.eraArt,
  })
}

const badgeEmoji = computed(() => {
  const b = props.version.badge
  if (!b) return null
  return BADGE_MAP[b] || null
})

// ── Swipe actions (mobile) ──
const swipe = useSwipeAction({
  onSwipeRight: () => {
    if (canStream.value) {
      playTrack(props.version, props.artistName, props.eraName, props.eraArt)
    }
  },
  onSwipeLeft: () => {
    addToQueue(props.version, props.artistName, props.eraName, props.eraArt)
  },
})

// ── Long press → context menu (mobile) ──
const { onTouchStart: longPressStart, onTouchEnd: longPressEnd } = useLongPress((x, y) => {
  showContextMenu({
    x,
    y,
    song: props.parentSong || undefined,
    version: props.version,
    artistName: props.artistName,
    artistSlug: props.artistSlug,
    sourceUrl: props.sourceUrl,
    eraName: props.eraName,
    eraArt: props.eraArt,
  })
})

function onTouchStart(e: TouchEvent) {
  swipe.onTouchStart(e)
  longPressStart(e)
}

function onTouchMove(e: TouchEvent) {
  swipe.onTouchMove(e)
}

function onTouchEnd(e: TouchEvent) {
  swipe.onTouchEnd(e)
  longPressEnd(e)
}

const _EMPTY_STYLE = {}
const swipeStyle = computed(() => {
  if (!swipe.isSwiping.value || swipe.offsetX.value === 0) return _EMPTY_STYLE
  return { transform: `translateX(${swipe.offsetX.value}px)`, transition: 'none' }
})

</script>

<template>
  <button
    class="version-row"
    :class="{ playing: isCurrentTrack && !isCurrentLoading, loading: isCurrentLoading }"
    :style="swipeStyle"
    @click="handlePlay"
    @contextmenu="handleContextMenu"
    @touchstart.passive="onTouchStart"
    @touchmove="onTouchMove"
    @touchend="onTouchEnd"
    @touchcancel="swipe.onTouchCancel"
  >
    <div class="v-content">
      <!-- Title line -->
      <div class="v-title-line">
        <span class="v-badge-slot">{{ (isCurrentTrack || isCurrentLoading) ? '' : (badgeEmoji || '') }}</span>
        <div class="v-title-inner">
          <span class="v-title">{{ version.name }}</span>
          <span v-if="version.version_tag" class="v-tag">[{{ version.version_tag }}]</span>
          <BadgeRow :version="version" />
        </div>
      </div>

      <!-- Credits lines -->
      <CreditTags :version="version" />

      <div v-if="!hideAltTitles && version.alt_titles?.length" class="v-alt-titles">
        <span v-for="(alt, i) in version.alt_titles" :key="'alt_' + i + '_' + alt" class="v-alt-item">{{ alt }}</span>
      </div>
    </div>

    <div class="v-right">
      <span v-if="version.track_length" class="v-length">
        {{ version.track_length }}
      </span>
      <!-- Mobile-only three-dot menu button -->
      <button
        class="mobile-menu-btn"
        aria-label="Options"
        @click.stop="handleMobileMenu"
      >
        <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
          <path fill="currentColor" d="M8 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM1.5 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zm13 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"/>
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
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
  font-size: 13px;
  border: 1px solid transparent;
  -webkit-tap-highlight-color: transparent;
}

.version-row:hover {
  background: rgba(255, 255, 255, 0.02);
  border-color: rgba(255, 255, 255, 0.03);
  border-left-color: hsl(var(--primary) / 0.3);
  border-left-width: 2px;
  transform: translateX(1px);
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

/* Single pulsing bar for buffering/loading state */
.version-row.loading .v-badge-slot {
  display: flex;
  align-items: center;
  justify-content: center;
}

.version-row.loading .v-badge-slot::before {
  content: '';
  display: block;
  width: 2px;
  height: 8px;
  border-radius: 1px;
  background: hsl(var(--primary));
  animation: eq-bar 0.6s ease-in-out infinite alternate;
  opacity: 0.6;
}

.v-content {
  flex: 1;
  min-width: 0;
  --metadata-indent: 24px;
}

.v-title-line {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  font-size: 13px;
  font-weight: 400;
  color: var(--text-secondary);
  line-height: 1.4;
}

.v-title-inner {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 10px;
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
  flex-shrink: 1;
}

.v-tag {
  color: var(--text-dim);
  font-size: 11px;
  flex-shrink: 0;
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
  padding-left: var(--metadata-indent, 0px);
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

.mobile-menu-btn {
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

.mobile-menu-btn:active {
  background: rgba(255, 255, 255, 0.15);
  color: rgba(255, 255, 255, 0.9);
}

@media (hover: none) and (pointer: coarse) {
  .mobile-menu-btn {
    display: flex;
  }
}

@media (max-width: 640px) {
  .version-row { font-size: 13px; gap: 6px; padding: 10px 8px; min-height: 44px; }
  .v-title-line { font-size: 13px; }
  .v-length { font-size: 12px; }
  .v-title { min-width: 60px; }
}
</style>
