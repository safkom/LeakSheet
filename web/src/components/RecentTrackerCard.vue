<script setup lang="ts">
import type { RecentTracker } from '../composables/useRecentTrackers'

const props = defineProps<{
  entry: RecentTracker
}>()

defineEmits<{
  click: []
}>()

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map(w => w[0]?.toUpperCase() ?? '')
    .join('')
}
</script>

<template>
  <button class="recent-card" @click="$emit('click')" type="button">
    <!-- Thumbnail -->
    <div class="thumb">
      <img
        v-if="entry.artUrl"
        :src="`/api/image-proxy?url=${encodeURIComponent(entry.artUrl)}`"
        :alt="entry.name"
        class="thumb-img"
        loading="lazy"
      />
      <div v-else class="thumb-placeholder">{{ initials(entry.name) }}</div>
    </div>

    <!-- Info -->
    <div class="info">
      <span class="artist-name">{{ entry.name }}</span>
      <span class="stat-line">
        {{ entry.total_songs.toLocaleString() }} songs
        <template v-if="entry.stats?.available">
          · {{ entry.stats.available.toLocaleString() }} available
        </template>
        <template v-if="entry.stats?.snippets">
          · {{ entry.stats.snippets.toLocaleString() }} snippets
        </template>
      </span>
    </div>

    <!-- Chevron -->
    <svg class="chevron" viewBox="0 0 16 16" width="14" height="14">
      <path fill="currentColor" d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06z"/>
    </svg>
  </button>
</template>

<style scoped>
.recent-card {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 10px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, transform 0.15s, box-shadow 0.15s;
  -webkit-tap-highlight-color: transparent;
}

.recent-card:hover {
  background: hsl(0 0% 9%);
  border-color: rgba(255, 255, 255, 0.12);
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}

.recent-card:active {
  transform: scale(0.98);
  box-shadow: none;
}

/* Thumbnail */
.thumb {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  border-radius: 8px;
  overflow: hidden;
  background: hsl(0 0% 12%);
}

.thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-secondary);
  background: linear-gradient(135deg, hsl(0 0% 14%), hsl(0 0% 10%));
  letter-spacing: 0.5px;
}

/* Info */
.info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.artist-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-line {
  font-size: 11px;
  color: var(--text-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Chevron */
.chevron {
  flex-shrink: 0;
  color: var(--text-dim);
  opacity: 0.5;
  transition: opacity 0.15s, transform 0.15s;
}

.recent-card:hover .chevron {
  opacity: 1;
  transform: translateX(2px);
}
</style>
