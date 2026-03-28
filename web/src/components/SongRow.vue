<script setup lang="ts">
import { computed, ref, type PropType } from 'vue'
import VersionRow from './VersionRow.vue'
import BadgeRow from './BadgeRow.vue'
import CreditTags from './CreditTags.vue'
import { playTrack, isStreamable, playerState, isTrackMatch } from '../composables/usePlayer'
import { BADGE_MAP } from '../composables/useUtils'
import { useSharedOverlays } from '../composables/useSharedOverlays'
import type { Song } from '../composables/useEraFiltering'

const props = defineProps({
  song: { type: Object as PropType<Song>, required: true },
  expanded: Boolean,
  artistName: String,
  artistSlug: String,
  sourceUrl: { type: String as PropType<string | null>, default: null },
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

const isCurrentLoading = computed(() => isCurrentSong.value && playerState.loading)

const badgeEmoji = computed(() => {
  // Scan all versions to pick highest-priority badge: 'best' > 'special' > others
  const versions = props.song.versions || []
  if (versions.some(v => v.badge === 'best')) return BADGE_MAP['best'] || null
  if (versions.some(v => v.badge === 'special')) return BADGE_MAP['special'] || null
  const b = props.song.badge
  if (!b) return null
  return BADGE_MAP[b] || null
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
    song: props.song,
    version: firstVersion.value,
    artistName: props.artistName,
    artistSlug: props.artistSlug,
    sourceUrl: props.sourceUrl,
    eraName: props.eraName,
    eraArt: props.eraArt,
  })
}

</script>

<template>
  <div class="song-row-wrapper">
    <button
      class="song-row"
      :class="{ expanded, playing: isCurrentSong && !isCurrentLoading, loading: isCurrentLoading, 'confirmed-only': isConfirmedOnly && !hasMultipleVersions }"
      @click="handleClick"
      @contextmenu="handleContextMenu"
    >
      <div class="song-content">
        <!-- Title line -->
        <div class="song-title-line">
          <span class="badge-slot" :data-emoji="badgeEmoji || ''">{{ (isCurrentSong || isCurrentLoading) ? '' : (badgeEmoji || '') }}</span>
          <div class="song-title-inner">
            <span class="song-title">{{ song.base_name }}</span>
            <BadgeRow v-if="!hasMultipleVersions && firstVersion" :version="firstVersion" />
            <!-- Expand chevron for multi-version -->
            <svg v-if="hasMultipleVersions" viewBox="0 0 16 16" width="12" height="12" class="expand-chevron" :class="{ rotated: expanded }">
              <path fill="currentColor" d="M4.427 7.427l3.396 3.396a.25.25 0 0 0 .354 0l3.396-3.396A.25.25 0 0 0 11.396 7H4.604a.25.25 0 0 0-.177.427z"/>
            </svg>
          </div>
        </div>

        <!-- Alt titles for multi-version songs (shown on parent, not per-version) -->
        <div v-if="hasMultipleVersions && allAltTitles.length" class="song-alt-titles">
          <span v-for="(alt, i) in allAltTitles" :key="'alt_' + i + '_' + alt" class="alt-title"><span class="alt-title-inner">{{ alt }}</span></span>
        </div>

        <!-- Credits lines -->
        <template v-if="!hasMultipleVersions && firstVersion">
          <CreditTags :version="firstVersion" />
          <div v-if="firstVersion.alt_titles?.length" class="song-alt-titles">
            <span v-for="(alt, i) in firstVersion.alt_titles" :key="'falt_' + i + '_' + alt" class="alt-title">{{ alt }}</span>
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
        <!-- Mobile-only three-dot menu button -->
        <button
          class="mobile-menu-btn"
          aria-label="Options"
          @click.stop="handleMobileMenu"
        >
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <path fill="currentColor" d="M8 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM1.5 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zm13 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"/>
          </svg>
        </button>
      </div>
    </button>

    <!-- Accordion: version list -->
    <Transition name="versions">
      <div v-if="expanded && hasMultipleVersions" class="versions-panel">
        <div class="versions-panel-inner">
          <VersionRow
            v-for="(v, i) in song.versions"
            :key="v.name + '_' + i"
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
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
  border: 1px solid transparent;
  -webkit-tap-highlight-color: transparent;
  text-align: left;
}

.song-row:hover {
  background: rgba(255, 255, 255, 0.025);
  border-color: rgba(255, 255, 255, 0.05);
  border-left-color: hsl(var(--primary) / 0.4);
  border-left-width: 2px;
  transform: translateX(1px);
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

/* Equalizer animation for playing state — @keyframes eq-bar defined globally in style.css */
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

/* Single pulsing bar for buffering/loading state */
.song-row.loading .badge-slot {
  display: flex;
  align-items: center;
  justify-content: center;
}

.song-row.loading .badge-slot::before {
  content: '';
  display: block;
  width: 2.5px;
  height: 10px;
  border-radius: 1px;
  background: hsl(var(--primary));
  animation: eq-bar 0.6s ease-in-out infinite alternate;
  opacity: 0.6;
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
  --metadata-indent: 24px;
}

.song-title-line {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.4;
}

.song-title-inner {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 14px;
}

.song-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex-shrink: 1;
}

.badge-slot {
  width: 20px;
  min-width: 20px;
  font-size: 14px;
  flex-shrink: 0;
  text-align: center;
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
  padding-left: var(--metadata-indent, 0px);
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

/* Mobile-only three-dot menu button: hidden on hover devices, shown on touch */
.mobile-menu-btn {
  display: none;
  align-items: center;
  justify-content: center;
  padding: 6px;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
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
  .song-row { padding: 10px 8px; }
  .song-title-line { font-size: 14px; }
  .song-title {
    white-space: normal;
    overflow: visible;
    text-overflow: unset;
  }
  .track-length { font-size: 13px; }
  .versions-panel { padding-left: 12px; }
}


</style>
