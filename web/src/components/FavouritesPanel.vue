<script setup lang="ts">
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import { favouritesByArtist, clearFavourites, removeFavourite, favourites } from '../composables/useFavourites'
import { playTrack, isStreamable, addToQueue } from '../composables/usePlayer'
import { toast } from 'vue-sonner'

const emit = defineEmits(['close'])

const grouped = computed(() => favouritesByArtist())
const isEmpty = computed(() => favourites.value.length === 0)

function handlePlay(entry: ReturnType<typeof favouritesByArtist>[0]['eras'][0]['entries'][0]) {
  const streamable = entry.song.versions.find(v => isStreamable(v))
  if (streamable) {
    playTrack(streamable, entry.artistName, entry.eraName, entry.eraArt || undefined)
    emit('close')
  }
}

function handleQueue(entry: ReturnType<typeof favouritesByArtist>[0]['eras'][0]['entries'][0]) {
  const streamable = entry.song.versions.find(v => isStreamable(v))
  if (streamable) {
    addToQueue(streamable, entry.artistName, entry.eraName, entry.eraArt || '')
    toast.success('Added to queue')
  }
}

function handleRemove(key: string) {
  removeFavourite(key)
}

function handleClearAll() {
  clearFavourites()
}

function canPlay(entry: ReturnType<typeof favouritesByArtist>[0]['eras'][0]['entries'][0]): boolean {
  return entry.song.versions.some(v => isStreamable(v))
}

function primaryBadge(entry: ReturnType<typeof favouritesByArtist>[0]['eras'][0]['entries'][0]): string {
  const BADGE_EMOJI: Record<string, string> = {
    best: '⭐',
    special: '✨',
    grail: '🏆',
    wanted: '🥇',
    worst: '🗑️',
    ai: '🤖',
  }
  const badge = entry.song.badge || entry.song.versions[0]?.badge
  return badge ? (BADGE_EMOJI[badge] || '') : ''
}

function primaryQuality(entry: ReturnType<typeof favouritesByArtist>[0]['eras'][0]['entries'][0]): string {
  return entry.song.quality || entry.song.versions[0]?.quality || ''
}
</script>

<template>
  <Teleport to="body">
    <div class="fav-backdrop" @click.self="emit('close')">
      <div class="fav-panel" role="dialog" aria-label="Favourites">
        <!-- Header -->
        <div class="fav-header">
          <div class="fav-header-left">
            <svg viewBox="0 0 16 16" width="16" height="16" class="fav-header-icon">
              <path fill="currentColor" d="M7.655 14.916 3 10.449a4.004 4.004 0 0 1 0-5.797 4.006 4.006 0 0 1 5.83.32 4.007 4.007 0 0 1 5.83-.32 4.005 4.005 0 0 1 0 5.797l-4.655 4.467a.75.75 0 0 1-1.35 0z"/>
            </svg>
            <h3 class="fav-title">Favourites</h3>
            <span v-if="!isEmpty" class="fav-count">{{ favourites.length }}</span>
          </div>
          <div class="fav-header-actions">
            <Button
              v-if="!isEmpty"
              variant="ghost"
              size="sm"
              class="clear-btn"
              @click="handleClearAll"
            >Clear all</Button>
            <button class="fav-close" @click="emit('close')" aria-label="Close favourites">
              <svg viewBox="0 0 16 16" width="14" height="14">
                <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- Empty state -->
        <div v-if="isEmpty" class="fav-empty">
          <svg viewBox="0 0 16 16" width="32" height="32" class="fav-empty-icon">
            <path fill="currentColor" d="m8 14.25.345.666a.75.75 0 0 1-.69 0l-.008-.004-.018-.01a7.152 7.152 0 0 1-.31-.17 22.055 22.055 0 0 1-3.434-2.414C2.045 10.731 0 8.35 0 5.5 0 2.836 2.086 1 4.25 1 5.797 1 7.153 1.802 8 3.02 8.847 1.802 10.203 1 11.75 1 13.914 1 16 2.836 16 5.5c0 2.85-2.045 5.231-3.885 6.818a22.066 22.066 0 0 1-3.744 2.584l-.018.01-.006.003h-.002ZM4.25 2.5c-1.336 0-2.75 1.164-2.75 3 0 2.15 1.58 4.144 3.365 5.682A20.58 20.58 0 0 0 8 13.393a20.58 20.58 0 0 0 3.135-2.211C12.92 9.644 14.5 7.65 14.5 5.5c0-1.836-1.414-3-2.75-3-1.373 0-2.609.986-3.029 2.456a.749.749 0 0 1-1.442 0C6.859 3.486 5.623 2.5 4.25 2.5Z"/>
          </svg>
          <p>No favourites yet</p>
          <p class="fav-empty-hint">Click ♥ on any song to save it here</p>
        </div>

        <!-- Grouped list -->
        <div v-else class="fav-list">
          <div v-for="artist in grouped" :key="artist.artistSlug" class="fav-artist-group">
            <!-- Artist header -->
            <div class="fav-artist-header">
              <span class="fav-artist-name">{{ artist.artistName }}</span>
            </div>

            <!-- Era groups -->
            <div v-for="eraGroup in artist.eras" :key="eraGroup.eraName" class="fav-era-group">
              <div class="fav-era-header">
                <img
                  v-if="eraGroup.eraArt"
                  :src="`/api/image-proxy?url=${encodeURIComponent(eraGroup.eraArt)}`"
                  class="fav-era-art"
                  alt=""
                  loading="lazy"
                />
                <span class="fav-era-name">{{ eraGroup.eraName }}</span>
              </div>

              <!-- Song entries -->
              <div
                v-for="entry in eraGroup.entries"
                :key="entry.key"
                class="fav-entry"
              >
                <span class="fav-entry-badge">{{ primaryBadge(entry) }}</span>
                <div class="fav-entry-info">
                  <span class="fav-entry-name">{{ entry.song.base_name }}</span>
                  <span v-if="primaryQuality(entry)" class="fav-entry-quality">{{ primaryQuality(entry) }}</span>
                </div>
                <div class="fav-entry-actions">
                  <!-- Play button (only if streamable) -->
                  <button
                    v-if="canPlay(entry)"
                    class="fav-action-btn play-btn"
                    aria-label="Play"
                    @click="handlePlay(entry)"
                  >
                    <svg viewBox="0 0 16 16" width="12" height="12">
                      <path fill="currentColor" d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0zm4.879-2.773 4.264 2.559a.25.25 0 0 1 0 .428l-4.264 2.559A.25.25 0 0 1 6 10.559V5.442a.25.25 0 0 1 .379-.215z"/>
                    </svg>
                  </button>
                  <!-- Queue button -->
                  <button
                    v-if="canPlay(entry)"
                    class="fav-action-btn"
                    aria-label="Add to queue"
                    @click="handleQueue(entry)"
                  >
                    <svg viewBox="0 0 16 16" width="12" height="12">
                      <path fill="currentColor" d="M2 2.75A.75.75 0 0 1 2.75 2h10.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 2.75zm0 5A.75.75 0 0 1 2.75 7h7.5a.75.75 0 0 1 0 1.5h-7.5A.75.75 0 0 1 2 7.75zM2.75 12a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5z"/>
                    </svg>
                  </button>
                  <!-- Remove button -->
                  <button
                    class="fav-action-btn remove-btn"
                    aria-label="Remove from favourites"
                    @click="handleRemove(entry.key)"
                  >
                    <svg viewBox="0 0 16 16" width="12" height="12">
                      <path fill="currentColor" d="M7.655 14.916 3 10.449a4.004 4.004 0 0 1 0-5.797 4.006 4.006 0 0 1 5.83.32 4.007 4.007 0 0 1 5.83-.32 4.005 4.005 0 0 1 0 5.797l-4.655 4.467a.75.75 0 0 1-1.35 0z"/>
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.fav-backdrop {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-queue, 210) + 10);
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
}

.fav-panel {
  background: hsl(var(--card));
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-right: none;
  border-top: none;
  border-radius: 0 0 0 12px;
  width: 360px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: -8px 8px 32px rgba(0, 0, 0, 0.5);
  animation: fav-slide-in 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes fav-slide-in {
  from { opacity: 0; transform: translateY(-12px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Header */
.fav-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
  flex-shrink: 0;
}

.fav-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.fav-header-icon {
  color: var(--favourite-color, #e84057);
  flex-shrink: 0;
}

.fav-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.fav-count {
  font-size: 11px;
  color: var(--text-dim);
  background: rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 1px 7px;
}

.fav-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.clear-btn {
  font-size: 12px;
  color: var(--text-secondary);
  height: 28px;
  padding: 0 8px;
}

.clear-btn:hover {
  color: var(--text-primary);
}

.fav-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  color: var(--text-secondary);
  transition: color 0.15s, background 0.15s;
}

.fav-close:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.08);
}

/* Empty state */
.fav-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 20px;
  color: var(--text-secondary);
  font-size: 14px;
  text-align: center;
}

.fav-empty-icon {
  opacity: 0.25;
  margin-bottom: 4px;
}

.fav-empty-hint {
  font-size: 12px;
  color: var(--text-dim);
}

/* List */
.fav-list {
  overflow-y: auto;
  flex: 1;
  padding: 8px 0;
}

.fav-artist-group {
  margin-bottom: 4px;
}

.fav-artist-header {
  padding: 8px 16px 4px;
  position: sticky;
  top: 0;
  background: hsl(var(--card));
  z-index: 1;
}

.fav-artist-name {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--text-dim);
}

.fav-era-group {
  margin-bottom: 4px;
}

.fav-era-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px 3px;
}

.fav-era-art {
  width: 20px;
  height: 20px;
  border-radius: 3px;
  object-fit: cover;
  flex-shrink: 0;
  opacity: 0.85;
}

.fav-era-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Individual entry */
.fav-entry {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 16px 7px 28px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  transition: background 0.1s;
}

.fav-entry:last-child {
  border-bottom: none;
}

.fav-entry:hover {
  background: rgba(255, 255, 255, 0.03);
}

.fav-entry-badge {
  font-size: 13px;
  width: 18px;
  flex-shrink: 0;
  text-align: center;
}

.fav-entry-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.fav-entry-name {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 400;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fav-entry-quality {
  font-size: 10px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.fav-entry-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}

.fav-entry:hover .fav-entry-actions {
  opacity: 1;
}

.fav-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 5px;
  color: var(--text-secondary);
  transition: color 0.15s, background 0.15s;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.fav-action-btn:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.08);
}

.play-btn:hover {
  color: hsl(var(--primary));
}

.remove-btn:hover {
  color: var(--favourite-color, #e84057);
}

/* Mobile: bottom sheet, actions always visible */
@media (max-width: 640px) {
  .fav-backdrop {
    align-items: flex-end;
    justify-content: stretch;
  }

  .fav-panel {
    width: 100%;
    max-height: 70vh;
    border-radius: 12px 12px 0 0;
    border-right: 1px solid rgba(255, 255, 255, 0.1);
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    border-bottom: none;
    animation: fav-slide-up 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @keyframes fav-slide-up {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .fav-entry-actions {
    opacity: 1;
  }
}
</style>
