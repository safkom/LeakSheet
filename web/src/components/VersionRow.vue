<script setup>
import { computed, ref } from 'vue'
import ContextMenu from './ContextMenu.vue'
import SongDescriptionModal from './SongDescriptionModal.vue'
import { Badge } from '@/components/ui/badge'
import { playTrack, isStreamable, playerState, isTrackMatch } from '../composables/usePlayer'
import { effectiveBadge, availabilityVariant, BADGE_MAP } from '../composables/useUtils'

const props = defineProps({
  version: Object,
  artistName: String,
  eraName: String,
  eraArt: String,
  hideAltTitles: Boolean,
})

const canStream = computed(() => isStreamable(props.version))

const isCurrentTrack = computed(() => isTrackMatch(props.version))

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
      return { text: avail, variant: availabilityVariant(avail) }
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
    <div class="v-content">
      <!-- Title line -->
      <div class="v-title-line">
        <!-- Equalizer when playing -->
        <svg v-if="isCurrentTrack && playerState.isPlaying" viewBox="0 0 16 16" width="12" height="12" class="eq-icon inline-eq">
          <rect class="eq-bar eq-1" x="1" y="6" width="3" height="10" rx="1" fill="currentColor"/>
          <rect class="eq-bar eq-2" x="6" y="3" width="3" height="13" rx="1" fill="currentColor"/>
          <rect class="eq-bar eq-3" x="11" y="5" width="3" height="11" rx="1" fill="currentColor"/>
        </svg>
        <span v-if="badgeEmoji" class="v-badge">{{ badgeEmoji }}</span>
        <span class="v-title">{{ version.name }}</span>
        <span v-if="version.version_tag" class="v-tag">[{{ version.version_tag }}]</span>
        <Badge v-if="badge" :variant="badge.variant">{{ badge.text }}</Badge>
        <Badge v-if="availBadge" :variant="availBadge.variant">{{ availBadge.text }}</Badge>
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
  gap: 0;
  padding: 8px 8px;
  border-radius: var(--radius-md);
  transition: all 0.2s ease;
  font-size: 13px;
  border: 1px solid transparent;
}

.version-row:hover {
  background: rgba(255, 255, 255, 0.02);
  border-color: rgba(255, 255, 255, 0.03);
  transform: translateX(2px);
}

.version-row.playing {
  background: rgba(88, 166, 255, 0.05);
  border-color: rgba(88, 166, 255, 0.1);
}

.inline-eq {
  flex-shrink: 0;
  margin-right: 2px;
}

/* Equalizer animation */
.eq-icon { color: var(--accent-color); }
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

/* quality-badge, q-*, avail-pill, a-* base classes are in global style.css */
/* VersionRow-specific size overrides */
.quality-badge { font-size: 9px; padding: 1px 5px; }
.avail-pill { font-size: 9px; padding: 1px 5px; }

.v-length {
  color: var(--text-secondary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .version-row { font-size: 11px; gap: 6px; }
  .quality-badge, .avail-pill { font-size: 8px; }
}
</style>
