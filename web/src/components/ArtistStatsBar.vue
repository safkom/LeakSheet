<script setup lang="ts">
import type { ArtistStats } from '../composables/useEraStats'

defineProps<{
  stats: ArtistStats
}>()
</script>

<template>
  <div class="stats-bar">
    <span class="stat">
      <span class="stat-value">{{ stats.total.toLocaleString() }}</span>
      <span class="stat-label">total</span>
    </span>
    <span class="sep">·</span>
    <span class="stat">
      <span class="stat-value">{{ stats.available.toLocaleString() }}</span>
      <span class="stat-label">available</span>
    </span>
    <span class="sep">·</span>
    <span class="stat">
      <span class="stat-value">{{ stats.snippets.toLocaleString() }}</span>
      <span class="stat-label">snippets</span>
    </span>
    <span class="sep">·</span>
    <span class="stat">
      <span class="stat-value">{{ stats.fullHQ.toLocaleString() }}</span>
      <span class="stat-label">full HQ</span>
    </span>
  </div>
</template>

<style scoped>
.stats-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  animation: stats-fade 0.3s ease both;
}

@keyframes stats-fade {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .stats-bar { animation: none; }
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 3px;
}

.stat-value {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: 11px;
  color: var(--text-dim);
}

.sep {
  font-size: 11px;
  color: var(--text-dim);
  opacity: 0.5;
}
</style>
