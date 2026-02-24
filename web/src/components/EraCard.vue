<script setup>
import { computed } from 'vue'

const props = defineProps({
  era: Object,
  expanded: Boolean,
})

const emit = defineEmits(['click'])

const stats = computed(() => {
  const s = props.era.stats_raw
  if (!s) return null
  return s
})

const artSrc = computed(() => {
  if (!props.era.art_url) return null
  // Google Sheets image URLs: may be relative or lh* URLs
  const url = props.era.art_url
  if (url.startsWith('http')) return url
  if (url.startsWith('//')) return 'https:' + url
  return url
})
</script>

<template>
  <button
    class="era-card"
    :class="{ expanded }"
    @click="emit('click')"
  >
    <div class="era-art" v-if="artSrc">
      <img :src="artSrc" alt="" loading="lazy" />
    </div>
    <div class="era-art era-art-placeholder" v-else>
      <svg viewBox="0 0 24 24" width="24" height="24">
        <path fill="currentColor" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55C7.79 13 6 14.79 6 17s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
      </svg>
    </div>

    <div class="era-info">
      <h3 class="era-name">{{ era.name }}</h3>
      <div v-if="era.timeline?.length" class="era-timeline">
        <div v-for="(evt, i) in era.timeline.slice(0, 3)" :key="i" class="timeline-event">
          <span class="timeline-date">{{ evt.date }}</span>
          <span class="timeline-sep">&mdash;</span>
          <span class="timeline-text">{{ evt.event }}</span>
        </div>
      </div>
      <p v-if="era.description" class="era-desc">{{ era.description }}</p>
      <div class="era-stats-row">
        <span class="stat">{{ era.song_count }} songs</span>
        <span class="stat">{{ era.version_count }} versions</span>
      </div>
    </div>

    <div class="era-chevron">
      <svg
        viewBox="0 0 16 16"
        width="16"
        height="16"
        :class="{ rotated: expanded }"
      >
        <path fill="currentColor" d="M4.427 7.427l3.396 3.396a.25.25 0 0 0 .354 0l3.396-3.396A.25.25 0 0 0 11.396 7H4.604a.25.25 0 0 0-.177.427z"/>
      </svg>
    </div>
  </button>
</template>

<style scoped>
.era-card {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  text-align: left;
  transition: all 0.15s ease;
}

.era-card:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
}

.era-card.expanded {
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  border-color: var(--border-hover);
  background: var(--bg-card-hover);
}

.era-art {
  width: 64px;
  height: 64px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  flex-shrink: 0;
  background: var(--bg-secondary);
}

.era-art img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.era-art-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
}

.era-info {
  flex: 1;
  min-width: 0;
}

.era-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.era-desc {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 4px;
}

.era-timeline {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 4px;
}

.timeline-event {
  font-size: 11px;
  line-height: 1.3;
  display: flex;
  gap: 4px;
  overflow: hidden;
}

.timeline-date {
  color: var(--accent);
  font-weight: 500;
  flex-shrink: 0;
  opacity: 0.8;
}

.timeline-sep {
  color: var(--text-dim);
  opacity: 0.4;
  flex-shrink: 0;
}

.timeline-text {
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.era-stats-row {
  display: flex;
  gap: 12px;
}

.stat {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.era-chevron {
  flex-shrink: 0;
  color: var(--text-dim);
  transition: color 0.15s;
}

.era-card:hover .era-chevron {
  color: var(--accent);
}

.era-chevron svg {
  transition: transform 0.2s ease;
}

.era-chevron .rotated {
  transform: rotate(180deg);
}

@media (max-width: 640px) {
  .era-card { padding: 10px 12px; gap: 12px; }
  .era-art { width: 48px; height: 48px; }
  .era-name { font-size: 14px; }
  .era-desc { display: none; }
}
</style>
