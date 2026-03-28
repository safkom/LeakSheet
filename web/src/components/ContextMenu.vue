<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, type PropType } from 'vue'
import { toast } from 'vue-sonner'
import { addToQueue } from '../composables/usePlayer'
import { downloadFile } from '../composables/useDownload'
import { fetchMetadata, formatMetadataSummary, isLargeFile, type FileMetadata } from '../composables/useMetadata'
import { isFavourited, toggleFavourite } from '../composables/useFavourites'
import type { Song, SongVersion } from '../composables/useEraFiltering'

// Module-level controller so the download fetch survives component unmounting.
// (ContextMenu closes immediately after Download is clicked, which would abort
// a component-ref-based controller via onUnmounted.)
let _activeDownloadController: AbortController | null = null

const props = defineProps({
  x: Number,
  y: Number,
  song: { type: Object as PropType<Song> },
  version: { type: Object as PropType<SongVersion> },
  eraArt: String,
  artistName: String,
  artistSlug: String,
  sourceUrl: { type: String as PropType<string | null>, default: null },
  eraName: String,
})

const emit = defineEmits(['close', 'show-description'])

const menuRef = ref<HTMLElement | null>(null)
const adjustedX = ref(props.x)
const adjustedY = ref(props.y)

onMounted(async () => {
  await nextTick()
  if (menuRef.value) {
    const rect = menuRef.value.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight

    // Account for player bar at bottom (~80px)
    const playerBar = document.querySelector('.player-bar')
    const bottomInset = playerBar ? playerBar.getBoundingClientRect().height : 0

    // Keep menu within viewport (above player bar)
    if (rect.right > vw) adjustedX.value = vw - rect.width - 8
    if (rect.bottom > vh - bottomInset) adjustedY.value = vh - bottomInset - rect.height - 8
    if (adjustedX.value < 0) adjustedX.value = 8
    if (adjustedY.value < 0) adjustedY.value = 8
  }

  // Use mousedown (not click) so outside-press closes the menu before any click
  // fires on underlying elements. The contains() check ensures pressing inside
  // the menu itself does NOT trigger a close.
  document.addEventListener('mousedown', handleOutsideMousedown)
  document.addEventListener('contextmenu', handleOutsideContextmenu)
  document.addEventListener('keydown', handleEscape)

  // Fetch metadata (instant if cached from prior use)
  const link = getLink()
  if (link) {
    fetchMetadata(link).then((m) => { fileMetadata.value = m })
  }
})

onUnmounted(() => {
  document.removeEventListener('mousedown', handleOutsideMousedown)
  document.removeEventListener('contextmenu', handleOutsideContextmenu)
  document.removeEventListener('keydown', handleEscape)
})

function handleOutsideMousedown(e: MouseEvent) {
  if (menuRef.value && !menuRef.value.contains(e.target as Node)) {
    emit('close')
  }
}

function handleOutsideContextmenu(e: Event) {
  if (menuRef.value && !menuRef.value.contains(e.target as Node)) {
    emit('close')
  }
}

function handleEscape(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

/** Get the first link from the version or song */
function getLink() {
  const v = props.version || props.song?.versions?.[0]
  return v?.links?.[0] || null
}

function copyLink() {
  const link = getLink()
  if (link) {
    navigator.clipboard.writeText(link).then(() => {
      toast.success('Link copied')
    }).catch(() => {
      toast.error('Failed to copy link')
    })
  }
  emit('close')
}

function showDescription() {
  emit('show-description', {
    song: props.song,
    version: props.version,
    artistName: props.artistName,
    eraName: props.eraName,
    eraArt: props.eraArt,
  })
  emit('close')
}

function openOriginalUrl() {
  const link = getLink()
  if (link) {
    window.open(link, '_blank', 'noopener')
  }
  emit('close')
}

function download() {
  const v = props.version || props.song?.versions?.[0]
  if (!v?.links?.length) return
  const link = v.links[0]
  const baseName = v.name || 'track'
  // Abort any previous in-flight download before starting a new one
  _activeDownloadController?.abort()
  _activeDownloadController = new AbortController()
  downloadFile(link, baseName, _activeDownloadController.signal)
  emit('close')
}

function queueTrack() {
  const v = props.version || props.song?.versions?.[0]
  if (!v) return
  addToQueue(v, props.artistName || '', props.eraName || '', props.eraArt || '')
  toast.success('Added to queue')
  emit('close')
}

const isFav = computed(() => {
  if (!props.artistSlug || !props.eraName) return false
  const baseName = props.song?.base_name || props.version?.name || ''
  return isFavourited(props.artistSlug, props.eraName, baseName)
})

function toggleFav() {
  const song = props.song || (props.version ? { base_name: props.version.name, versions: [props.version] } : null)
  if (!song || !props.artistSlug || !props.eraName) return
  const added = toggleFavourite(
    song,
    props.artistSlug,
    props.artistName || '',
    props.sourceUrl ?? null,
    props.eraName,
    props.eraArt || null,
  )
  toast.success(added ? 'Added to favourites' : 'Removed from favourites')
  emit('close')
}

const hasLink = computed(() => getLink() !== null)

// Metadata (fetched on mount, instant if cached)
const fileMetadata = ref<FileMetadata | null>(null)

const formatLabel = computed(() => {
  if (!fileMetadata.value) return null
  return formatMetadataSummary(fileMetadata.value)
})

const isLarge = computed(() => {
  if (!fileMetadata.value) return false
  return isLargeFile(fileMetadata.value)
})
</script>

<template>
  <Teleport to="body">
    <div
      ref="menuRef"
      class="context-menu"
      :style="{ left: adjustedX + 'px', top: adjustedY + 'px' }"
      @click.stop
      @contextmenu.prevent.stop
    >
      <button class="ctx-item" :class="{ disabled: !hasLink }" @click="copyLink">
        <svg viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M7.775 3.275a.75.75 0 0 0 1.06 1.06l1.25-1.25a2 2 0 1 1 2.83 2.83l-2.5 2.5a2 2 0 0 1-2.83 0 .75.75 0 0 0-1.06 1.06 3.5 3.5 0 0 0 4.95 0l2.5-2.5a3.5 3.5 0 0 0-4.95-4.95l-1.25 1.25zm-4.69 9.64a2 2 0 0 1 0-2.83l2.5-2.5a2 2 0 0 1 2.83 0 .75.75 0 0 0 1.06-1.06 3.5 3.5 0 0 0-4.95 0l-2.5 2.5a3.5 3.5 0 0 0 4.95 4.95l1.25-1.25a.75.75 0 0 0-1.06-1.06l-1.25 1.25a2 2 0 0 1-2.83 0z"/>
        </svg>
        <span>Copy Link</span>
      </button>

      <div class="ctx-divider"></div>

      <button class="ctx-item" @click="queueTrack">
        <svg viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M2 2.75A.75.75 0 0 1 2.75 2h10.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 2.75zm0 5A.75.75 0 0 1 2.75 7h7.5a.75.75 0 0 1 0 1.5h-7.5A.75.75 0 0 1 2 7.75zM2.75 12a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5z"/>
        </svg>
        <span>Add To Queue</span>
      </button>

      <button class="ctx-item" :class="{ 'fav-active': isFav }" @click="toggleFav">
        <svg v-if="isFav" viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M7.655 14.916 3 10.449a4.004 4.004 0 0 1 0-5.797 4.006 4.006 0 0 1 5.83.32 4.007 4.007 0 0 1 5.83-.32 4.005 4.005 0 0 1 0 5.797l-4.655 4.467a.75.75 0 0 1-1.35 0z"/>
        </svg>
        <svg v-else viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="m8 14.25.345.666a.75.75 0 0 1-.69 0l-.008-.004-.018-.01a7.152 7.152 0 0 1-.31-.17 22.055 22.055 0 0 1-3.434-2.414C2.045 10.731 0 8.35 0 5.5 0 2.836 2.086 1 4.25 1 5.797 1 7.153 1.802 8 3.02 8.847 1.802 10.203 1 11.75 1 13.914 1 16 2.836 16 5.5c0 2.85-2.045 5.231-3.885 6.818a22.066 22.066 0 0 1-3.744 2.584l-.018.01-.006.003h-.002ZM4.25 2.5c-1.336 0-2.75 1.164-2.75 3 0 2.15 1.58 4.144 3.365 5.682A20.58 20.58 0 0 0 8 13.393a20.58 20.58 0 0 0 3.135-2.211C12.92 9.644 14.5 7.65 14.5 5.5c0-1.836-1.414-3-2.75-3-1.373 0-2.609.986-3.029 2.456a.749.749 0 0 1-1.442 0C6.859 3.486 5.623 2.5 4.25 2.5Z"/>
        </svg>
        <span>{{ isFav ? 'Remove from Favourites' : 'Add to Favourites' }}</span>
      </button>

      <button class="ctx-item" @click="showDescription">
        <svg viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.744 3.744 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75zm7.251 10.324l.004-5.073-.002-2.253A2.25 2.25 0 0 0 5.003 2.5H1.5v9h3.757a3.75 3.75 0 0 1 1.994.574zM8.755 4.75l-.004 7.322a3.752 3.752 0 0 1 1.992-.572H14.5v-9h-3.495a2.25 2.25 0 0 0-2.25 2.25z"/>
        </svg>
        <span>Show Description</span>
      </button>

      <button class="ctx-item" :class="{ disabled: !hasLink }" @click="openOriginalUrl">
        <svg viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M3.75 2h3.5a.75.75 0 0 1 0 1.5h-3.5a.25.25 0 0 0-.25.25v8.5c0 .138.112.25.25.25h8.5a.25.25 0 0 0 .25-.25v-3.5a.75.75 0 0 1 1.5 0v3.5A1.75 1.75 0 0 1 12.25 14h-8.5A1.75 1.75 0 0 1 2 12.25v-8.5C2 2.784 2.784 2 3.75 2zm6.854-1h4.146a.25.25 0 0 1 .25.25v4.146a.25.25 0 0 1-.427.177L13.03 4.03 9.28 7.78a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042l3.75-3.75-1.543-1.543A.25.25 0 0 1 10.604 1z"/>
        </svg>
        <span>Open Original URL</span>
        <span v-if="formatLabel" class="ctx-format-hint" :class="{ warn: isLarge }">{{ formatLabel }}</span>
      </button>

      <div class="ctx-divider"></div>

      <button class="ctx-item" :class="{ disabled: !hasLink }" @click="download">
        <svg viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M2.75 14A1.75 1.75 0 0 1 1 12.25v-2.5a.75.75 0 0 1 1.5 0v2.5c0 .138.112.25.25.25h10.5a.25.25 0 0 0 .25-.25v-2.5a.75.75 0 0 1 1.5 0v2.5A1.75 1.75 0 0 1 13.25 14zM7.25 7.689V2a.75.75 0 0 1 1.5 0v5.689l1.97-1.969a.749.749 0 1 1 1.06 1.06l-3.25 3.25a.749.749 0 0 1-1.06 0L4.22 6.78a.749.749 0 1 1 1.06-1.06z"/>
        </svg>
        <span>Download</span>
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.context-menu {
  position: fixed;
  z-index: var(--z-popover);
  min-width: 200px;
  background: hsl(var(--popover));
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 4px 0;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), 0 2px 8px rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(16px);
  animation: ctx-in 0.12s ease-out;
}

@keyframes ctx-in {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.ctx-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  font-size: 13px;
  color: var(--text-primary);
  transition: background 0.1s;
  white-space: nowrap;
}

.ctx-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.ctx-item.disabled {
  opacity: 0.4;
  pointer-events: none;
  cursor: not-allowed;
  color: var(--text-dim);
}

.ctx-item.fav-active {
  color: var(--favourite-color, #e84057);
}

.ctx-item.fav-active svg {
  opacity: 1;
  color: var(--favourite-color, #e84057);
}

.ctx-item svg {
  flex-shrink: 0;
  opacity: 0.6;
}

.ctx-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.08);
  margin: 4px 0;
}

.ctx-format-hint {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-dim);
  padding: 1px 5px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
}

.ctx-format-hint.warn {
  color: #f0a020;
  background: rgba(240, 160, 32, 0.12);
}
</style>
