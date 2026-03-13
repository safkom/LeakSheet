<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { toast } from 'vue-sonner'
import SongDescriptionModal from './SongDescriptionModal.vue'
import QueuePanel from './QueuePanel.vue'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { playerState, togglePlay, stopTrack, seekTo, formatTime, artProxyUrl, addToQueue, playNext } from '../composables/usePlayer'
import { getEraColors } from '../composables/useEraColors'
import { BADGE_MAP } from '../composables/useUtils'

const track = computed(() => playerState.track)
const playing = computed(() => playerState.isPlaying)
const loading = computed(() => playerState.loading)
const error = computed(() => playerState.error)
const hasStream = computed(() => !!playerState.streamUrl)
const playDisabled = computed(() => !hasStream.value && !loading.value)

const playerArtSrc = computed(() => artProxyUrl(playerState.artUrl))
const artError = ref(false)

// Reset error state when art URL changes
watch(() => playerState.artUrl, () => { artError.value = false })

const displayBadge = computed(() => {
  const b = track.value?.badge
  if (!b) return ''
  return BADGE_MAP[b] || ''
})

const displayName = computed(() => {
  if (!track.value) return ''
  const parts = [track.value.name]
  if (track.value.version_tag) parts.push(`[${track.value.version_tag}]`)
  return parts.join(' ')
})

const displaySub = computed(() => {
  return playerState.eraName || ''
})

const currentTimeStr = computed(() => formatTime(playerState.currentTime))
const durationStr = computed(() => {
  if (playerState.duration > 0 && isFinite(playerState.duration)) return formatTime(playerState.duration)
  return track.value?.track_length || '--:--'
})

const progressPct = computed(() => {
  if (!playerState.duration || !isFinite(playerState.currentTime) || !isFinite(playerState.duration)) return 0
  return (playerState.currentTime / playerState.duration) * 100
})

const bufferedPct = computed(() => {
  const b = playerState.buffered
  return isFinite(b) ? b * 100 : 0
})

// Seek on progress bar click
const progressBar = ref(null)

function handleSeek(e) {
  if (!playerState.duration || !isFinite(playerState.duration) || !hasStream.value) return
  if (!progressBar.value) return
  const rect = progressBar.value.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  seekTo(ratio * playerState.duration)
}

// Description modal
const showDescModal = ref(false)

function openTrackDescription() {
  showDescModal.value = true
}

// Queue panel
const showQueue = ref(false)
const queueCount = computed(() => playerState.queue.length)

function getTrackLink() {
  return track.value?.links?.[0] || null
}

function copyLink() {
  const link = getTrackLink()
  if (link) {
    navigator.clipboard.writeText(link).then(() => {
      toast.success('Link copied')
    }).catch(() => {
      toast.error('Failed to copy link')
    })
  }
}

function openOriginalUrl() {
  const link = getTrackLink()
  if (link) {
    window.open(link, '_blank', 'noopener')
  }
}

function queueTrack() {
  if (!track.value) return
  addToQueue(track.value, playerState.artistName || '', playerState.eraName || '', playerState.artUrl || '')
  toast.success('Added to queue')
}

const _MIME_TO_EXT: Record<string, string> = {
  'audio/mp4': '.m4a',
  'audio/mpeg': '.mp3',
  'audio/ogg': '.ogg',
  'audio/wav': '.wav',
  'audio/flac': '.flac',
  'audio/aac': '.aac',
  'audio/x-m4a': '.m4a',
}

const downloadController = ref<AbortController | null>(null)

onUnmounted(() => {
  downloadController.value?.abort()
})

async function downloadTrack() {
  if (!track.value?.links?.length) return
  const link = track.value.links[0]
  const downloadUrl = `/api/stream?url=${encodeURIComponent(link)}&download=true`
  try {
    downloadController.value?.abort()
    downloadController.value = new AbortController()
    toast('Downloading...')
    const res = await fetch(downloadUrl, { signal: downloadController.value.signal })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    // Derive extension from Content-Type so FLAC/OGG/WAV files get the right name
    const ct = res.headers.get('content-type')?.split(';')[0].trim() || ''
    const ext = _MIME_TO_EXT[ct] || '.mp3'
    const blob = await res.blob()
    const objUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objUrl
    a.download = `${track.value.name || track.value.base_name || 'track'}${ext}`
    a.click()
    URL.revokeObjectURL(objUrl)
    toast.success('Download complete')
  } catch (e) {
    if (e?.name !== 'AbortError') toast.error('Download failed')
  }
}

const hasLink = computed(() => getTrackLink() !== null)

// Dynamic accent color from era
const playerAccentColor = computed(() => {
  const eraName = playerState.eraName
  if (!eraName) return null
  const colors = getEraColors(eraName)
  return colors?.accent || null
})

const playerBarStyle = computed(() => {
  const accent = playerAccentColor.value
  if (!accent) return {}
  return { '--player-accent': accent }
})
</script>

<template>
  <TooltipProvider :delay-duration="300">
    <div class="player-bar" :style="playerBarStyle" role="region" aria-label="Audio player">
      <!-- Progress bar at top — full width thin line -->
      <div
        class="progress-bar-top"
        ref="progressBar"
        @click="handleSeek"
        :class="{ disabled: !hasStream }"
      >
        <div class="progress-buffered" :style="{ width: bufferedPct + '%' }"></div>
        <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
        <div
          v-if="progressPct > 0"
          class="progress-thumb"
          :style="{ left: progressPct + '%' }"
        ></div>
      </div>

      <div class="player-inner">
        <!-- Album art -->
        <div class="player-art" v-if="track">
          <img
            v-if="playerArtSrc && !artError"
            :src="playerArtSrc"
            alt=""
            class="player-art-img"
            @error="artError = true"
          />
          <div v-else class="player-art-placeholder">
            <svg viewBox="0 0 24 24" width="22" height="22">
              <path fill="currentColor" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55C7.79 13 6 14.79 6 17s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
            </svg>
          </div>
        </div>

        <!-- Track info -->
        <div class="player-track-info">
          <div class="player-track-name">
            <span v-if="loading" class="loading-dot"></span>
            <span v-if="displayBadge" class="player-badge">{{ displayBadge }}</span>
            {{ displayName }}
          </div>
          <div class="player-track-sub">
            <template v-if="error">
              <span class="player-error">{{ error }}</span>
            </template>
            <template v-else>
              {{ displaySub }}
              <span v-if="hasStream" class="player-time-inline">
                {{ currentTimeStr }} / {{ durationStr }}
              </span>
            </template>
          </div>
        </div>

        <!-- Controls -->
        <div class="player-controls">
          <Tooltip>
            <TooltipTrigger as-child>
              <button
                class="ctrl-btn"
                :class="{ disabled: playDisabled }"
                :disabled="playDisabled"
                @click="togglePlay"
                :aria-label="playing ? 'Pause' : 'Play'"
              >
                <svg v-if="loading" class="spinner" viewBox="0 0 24 24" width="28" height="28">
                  <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2.5" stroke-dasharray="31.4" stroke-dashoffset="10" stroke-linecap="round"/>
                </svg>
                <svg v-else-if="!playing" viewBox="0 0 24 24" width="28" height="28">
                  <path fill="currentColor" d="M8 5v14l11-7z"/>
                </svg>
                <svg v-else viewBox="0 0 24 24" width="28" height="28">
                  <path fill="currentColor" d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
                </svg>
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">{{ playing ? 'Pause' : 'Play' }}</TooltipContent>
          </Tooltip>
        </div>

        <!-- Right side: queue + menu + close -->
        <div class="player-right">
          <!-- Queue toggle -->
          <Tooltip v-if="track">
            <TooltipTrigger as-child>
              <button class="menu-btn queue-toggle-btn" :class="{ active: showQueue }" @click="showQueue = !showQueue" aria-label="Toggle queue">
                <svg viewBox="0 0 16 16" width="14" height="14">
                  <path fill="currentColor" d="M2 2.75A.75.75 0 0 1 2.75 2h10.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 2.75zm0 5A.75.75 0 0 1 2.75 7h7.5a.75.75 0 0 1 0 1.5h-7.5A.75.75 0 0 1 2 7.75zM2.75 12a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5z"/>
                </svg>
                <span v-if="queueCount > 0" class="queue-badge">{{ queueCount }}</span>
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">Queue ({{ queueCount }})</TooltipContent>
          </Tooltip>

          <!-- More options dropdown -->
          <DropdownMenu v-if="track">
            <DropdownMenuTrigger as-child>
              <button class="menu-btn" aria-label="More options" title="More options">
                <svg viewBox="0 0 16 16" width="14" height="14">
                  <circle cx="8" cy="2" r="1.5" fill="currentColor"/>
                  <circle cx="8" cy="8" r="1.5" fill="currentColor"/>
                  <circle cx="8" cy="14" r="1.5" fill="currentColor"/>
                </svg>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="top" :side-offset="8" class="player-dropdown min-w-[200px]">
              <DropdownMenuItem :disabled="!hasLink" @select="copyLink">
                <svg viewBox="0 0 16 16" width="14" height="14" class="mr-2 opacity-60">
                  <path fill="currentColor" d="M7.775 3.275a.75.75 0 0 0 1.06 1.06l1.25-1.25a2 2 0 1 1 2.83 2.83l-2.5 2.5a2 2 0 0 1-2.83 0 .75.75 0 0 0-1.06 1.06 3.5 3.5 0 0 0 4.95 0l2.5-2.5a3.5 3.5 0 0 0-4.95-4.95l-1.25 1.25zm-4.69 9.64a2 2 0 0 1 0-2.83l2.5-2.5a2 2 0 0 1 2.83 0 .75.75 0 0 0 1.06-1.06 3.5 3.5 0 0 0-4.95 0l-2.5 2.5a3.5 3.5 0 0 0 4.95 4.95l1.25-1.25a.75.75 0 0 0-1.06-1.06l-1.25 1.25a2 2 0 0 1-2.83 0z"/>
                </svg>
                Copy Link
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem @select="queueTrack">
                <svg viewBox="0 0 16 16" width="14" height="14" class="mr-2 opacity-60">
                  <path fill="currentColor" d="M2 2.75A.75.75 0 0 1 2.75 2h10.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 2.75zm0 5A.75.75 0 0 1 2.75 7h7.5a.75.75 0 0 1 0 1.5h-7.5A.75.75 0 0 1 2 7.75zM2.75 12a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5z"/>
                </svg>
                Add to Queue
              </DropdownMenuItem>
              <DropdownMenuItem @select="openTrackDescription">
                <svg viewBox="0 0 16 16" width="14" height="14" class="mr-2 opacity-60">
                  <path fill="currentColor" d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.744 3.744 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75zm7.251 10.324l.004-5.073-.002-2.253A2.25 2.25 0 0 0 5.003 2.5H1.5v9h3.757a3.75 3.75 0 0 1 1.994.574zM8.755 4.75l-.004 7.322a3.752 3.752 0 0 1 1.992-.572H14.5v-9h-3.495a2.25 2.25 0 0 0-2.25 2.25z"/>
                </svg>
                Show Description
              </DropdownMenuItem>
              <DropdownMenuItem :disabled="!hasLink" @select="openOriginalUrl">
                <svg viewBox="0 0 16 16" width="14" height="14" class="mr-2 opacity-60">
                  <path fill="currentColor" d="M3.75 2h3.5a.75.75 0 0 1 0 1.5h-3.5a.25.25 0 0 0-.25.25v8.5c0 .138.112.25.25.25h8.5a.25.25 0 0 0 .25-.25v-3.5a.75.75 0 0 1 1.5 0v3.5A1.75 1.75 0 0 1 12.25 14h-8.5A1.75 1.75 0 0 1 2 12.25v-8.5C2 2.784 2.784 2 3.75 2zm6.854-1h4.146a.25.25 0 0 1 .25.25v4.146a.25.25 0 0 1-.427.177L13.03 4.03 9.28 7.78a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042l3.75-3.75-1.543-1.543A.25.25 0 0 1 10.604 1z"/>
                </svg>
                Open Original URL
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem :disabled="!hasLink" @select="downloadTrack">
                <svg viewBox="0 0 16 16" width="14" height="14" class="mr-2 opacity-60">
                  <path fill="currentColor" d="M2.75 14A1.75 1.75 0 0 1 1 12.25v-2.5a.75.75 0 0 1 1.5 0v2.5c0 .138.112.25.25.25h10.5a.25.25 0 0 0 .25-.25v-2.5a.75.75 0 0 1 1.5 0v2.5A1.75 1.75 0 0 1 13.25 14zM7.25 7.689V2a.75.75 0 0 1 1.5 0v5.689l1.97-1.969a.749.749 0 1 1 1.06 1.06l-3.25 3.25a.749.749 0 0 1-1.06 0L4.22 6.78a.749.749 0 1 1 1.06-1.06z"/>
                </svg>
                Download
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <Tooltip>
            <TooltipTrigger as-child>
              <button class="close-btn" @click="stopTrack" aria-label="Close player">
                <svg viewBox="0 0 16 16" width="14" height="14">
                  <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
                </svg>
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">Close player</TooltipContent>
          </Tooltip>
        </div>
      </div>
    </div>
  </TooltipProvider>

  <!-- Queue panel -->
  <QueuePanel v-if="showQueue" @close="showQueue = false" />

  <!-- Track description from player -->
  <SongDescriptionModal
    v-if="showDescModal && track"
    :version="track"
    :era-art="playerState.artUrl"
    :era-name="playerState.eraName"
    :artist-name="playerState.artistName"
    @close="showDescModal = false"
  />
</template>

<style scoped>
.player-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--bg-player);
  border-top: 1px solid var(--border-color);
  z-index: 200;
  backdrop-filter: blur(12px);
  padding-bottom: env(safe-area-inset-bottom, 0px);
}

/* Progress bar at top — full width thin line */
.progress-bar-top {
  position: relative;
  width: 100%;
  height: 3px;
  background: rgba(255,255,255,0.06);
  cursor: pointer;
  transition: height 0.15s ease;
}

.progress-bar-top::before {
  content: '';
  position: absolute;
  top: -10px;
  bottom: -10px;
  left: 0;
  right: 0;
}

.progress-bar-top:hover {
  height: 5px;
}

.progress-bar-top.disabled {
  cursor: default;
  opacity: 0.3;
}

.progress-buffered {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: rgba(255,255,255,0.08);
  transition: width 0.3s;
}

.progress-fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: var(--player-accent, var(--accent-color));
  transition: width 0.1s linear;
}

.progress-thumb {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--player-accent, var(--accent-color));
  opacity: 0;
  transition: opacity 0.15s;
}

.progress-bar-top:hover .progress-thumb {
  opacity: 1;
}

.player-inner {
  height: 68px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 14px;
}

/* Album art */
.player-art {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  border-radius: 6px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.05);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.player-art-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.player-art-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  opacity: 0.4;
}

.player-track-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.player-badge {
  flex-shrink: 0;
}

.player-track-name {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-primary);
}

.player-track-sub {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0.9;
}

.player-time-inline {
  color: var(--text-dim);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  margin-left: 8px;
}

.player-error {
  color: #f85149;
}

.player-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ctrl-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--player-accent, var(--accent-color));
  color: var(--bg-primary);
  transition: background 0.15s;
}

.ctrl-btn:hover {
  filter: brightness(1.15);
}

.ctrl-btn.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-dot::after {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-color);
  animation: pulse 1s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

.player-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* Touch-target safe buttons (min 44px hit area) */
.menu-btn,
.close-btn {
  color: var(--text-dim);
  width: 44px;
  height: 44px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.1s, background 0.1s;
  -webkit-tap-highlight-color: transparent;
}

.menu-btn:hover,
.close-btn:hover {
  color: var(--player-accent, var(--text-primary));
  background: rgba(255, 255, 255, 0.08);
}

.queue-toggle-btn {
  position: relative;
}

.queue-toggle-btn.active {
  color: var(--player-accent, var(--accent-color));
}

.queue-badge {
  position: absolute;
  top: 6px;
  right: 6px;
  min-width: 14px;
  height: 14px;
  font-size: 9px;
  font-weight: 700;
  line-height: 14px;
  text-align: center;
  padding: 0 3px;
  border-radius: 7px;
  background: var(--player-accent, var(--accent-color));
  color: var(--bg-primary);
  pointer-events: none;
}

@media (max-width: 640px) {
  .player-inner { height: 60px; padding: 0 10px; gap: 8px; }
  .player-track-name { font-size: 12px; }
  .ctrl-btn { width: 40px; height: 40px; }
  .player-right { gap: 4px; }
  .player-art { width: 40px; height: 40px; border-radius: 4px; }
  .player-time-inline { display: none; }
  .progress-bar-top { height: 4px; }
  .progress-bar-top .progress-thumb { opacity: 1; width: 14px; height: 14px; }
}
</style>

<!-- Unscoped override for portal-rendered dropdown menu -->
<style>
.player-dropdown {
  background: hsl(0 0% 12%) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.7), 0 0 0 1px rgba(255, 255, 255, 0.06) !important;
  backdrop-filter: none !important;
}
</style>
