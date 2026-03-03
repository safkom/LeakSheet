<script setup>
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import { playerState, removeFromQueue, clearQueue, moveInQueue, playFromQueue } from '../composables/usePlayer'

const emit = defineEmits(['close'])

const queue = computed(() => playerState.queue)
const isEmpty = computed(() => queue.value.length === 0)
</script>

<template>
  <Teleport to="body">
    <div class="queue-backdrop" @click.self="emit('close')">
      <div class="queue-panel" role="dialog" aria-label="Playback queue">
        <!-- Header -->
        <div class="queue-header">
          <h3 class="queue-title">Queue</h3>
          <div class="queue-header-actions">
            <Button
              v-if="!isEmpty"
              variant="ghost"
              size="sm"
              class="clear-btn"
              @click="clearQueue"
            >Clear all</Button>
            <button class="queue-close" @click="emit('close')" aria-label="Close queue">
              <svg viewBox="0 0 16 16" width="14" height="14">
                <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- Empty state -->
        <div v-if="isEmpty" class="queue-empty">
          <svg viewBox="0 0 16 16" width="24" height="24" class="queue-empty-icon">
            <path fill="currentColor" d="M2 2.75A.75.75 0 0 1 2.75 2h10.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 2.75zm0 5A.75.75 0 0 1 2.75 7h7.5a.75.75 0 0 1 0 1.5h-7.5A.75.75 0 0 1 2 7.75zM2.75 12a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5z"/>
          </svg>
          <p>Queue is empty</p>
          <p class="queue-empty-hint">Right-click a song and select "Add to Queue"</p>
        </div>

        <!-- Queue items -->
        <div v-else class="queue-list">
          <div
            v-for="(item, idx) in queue"
            :key="item.id"
            class="queue-item"
          >
            <span class="queue-idx">{{ idx + 1 }}</span>
            <div class="queue-item-info">
              <div class="queue-item-name">{{ item.version.name }}</div>
              <div class="queue-item-meta">{{ item.eraName }}</div>
            </div>
            <div class="queue-item-actions">
              <!-- Move up -->
              <button
                class="queue-action-btn"
                :disabled="idx === 0"
                @click="moveInQueue(idx, idx - 1)"
                aria-label="Move up"
              >
                <svg viewBox="0 0 16 16" width="12" height="12">
                  <path fill="currentColor" d="M3.47 7.78a.75.75 0 0 1 0-1.06l4.25-4.25a.75.75 0 0 1 1.06 0l4.25 4.25a.751.751 0 0 1-.018 1.042.751.751 0 0 1-1.042.018L9.22 5.06v7.19a.75.75 0 0 1-1.5 0V5.06L4.97 7.81a.75.75 0 0 1-1.06-.02l-.44-.01z"/>
                </svg>
              </button>
              <!-- Move down -->
              <button
                class="queue-action-btn"
                :disabled="idx === queue.length - 1"
                @click="moveInQueue(idx, idx + 1)"
                aria-label="Move down"
              >
                <svg viewBox="0 0 16 16" width="12" height="12">
                  <path fill="currentColor" d="M13.03 8.22a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L3.47 9.28a.751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018l2.75 2.75V3.75a.75.75 0 0 1 1.5 0v7.19l2.72-2.72a.75.75 0 0 1 1.06 0l.47.01z"/>
                </svg>
              </button>
              <!-- Play now -->
              <button
                class="queue-action-btn queue-play"
                @click="playFromQueue(idx)"
                aria-label="Play now"
              >
                <svg viewBox="0 0 24 24" width="14" height="14">
                  <path fill="currentColor" d="M8 5v14l11-7z"/>
                </svg>
              </button>
              <!-- Remove -->
              <button
                class="queue-action-btn queue-remove"
                @click="removeFromQueue(idx)"
                aria-label="Remove from queue"
              >
                <svg viewBox="0 0 16 16" width="12" height="12">
                  <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.queue-backdrop {
  position: fixed;
  inset: 0;
  z-index: 190;
  background: rgba(0, 0, 0, 0.4);
  animation: fade-in 0.15s ease;
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.queue-panel {
  position: fixed;
  bottom: calc(var(--player-height) + env(safe-area-inset-bottom, 0px));
  right: 16px;
  width: 340px;
  max-height: 400px;
  background: hsl(var(--popover));
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: slide-up 0.2s ease;
}

@keyframes slide-up {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.queue-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
}

.queue-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.queue-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.clear-btn {
  font-size: 12px !important;
  color: var(--text-secondary) !important;
  height: 28px !important;
  padding: 0 8px !important;
}

.clear-btn:hover {
  color: #f85149 !important;
}

.queue-close {
  color: var(--text-dim);
  padding: 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.queue-close:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.08);
}

/* Empty state */
.queue-empty {
  padding: 32px 16px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
}

.queue-empty-icon {
  color: var(--text-dim);
  margin-bottom: 8px;
}

.queue-empty-hint {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 4px;
}

/* Queue list */
.queue-list {
  overflow-y: auto;
  flex: 1;
  padding: 4px 0;
}

.queue-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px 8px 16px;
  transition: background 0.1s;
}

.queue-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.queue-idx {
  font-size: 11px;
  color: var(--text-dim);
  width: 16px;
  text-align: center;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.queue-item-info {
  flex: 1;
  min-width: 0;
}

.queue-item-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.queue-item-meta {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.queue-item-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.1s;
}

.queue-item:hover .queue-item-actions {
  opacity: 1;
}

.queue-action-btn {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  border-radius: 4px;
  transition: all 0.1s;
}

.queue-action-btn:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.08);
}

.queue-action-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.queue-action-btn:disabled:hover {
  background: transparent;
  color: var(--text-dim);
}

.queue-play:hover {
  color: var(--accent-color);
}

.queue-remove:hover {
  color: #f85149;
}

/* Mobile: full-width bottom sheet */
@media (max-width: 640px) {
  .queue-panel {
    right: 0;
    left: 0;
    bottom: calc(var(--player-height) + env(safe-area-inset-bottom, 0px));
    width: 100%;
    max-height: 50vh;
    border-radius: 12px 12px 0 0;
  }

  .queue-item-actions {
    opacity: 1;
  }
}
</style>
