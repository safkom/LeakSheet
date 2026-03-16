<script setup lang="ts">
import type { PropType } from 'vue'
import type { SongVersion } from '../composables/useEraFiltering'

defineProps({
  version: { type: Object as PropType<SongVersion>, required: true },
})
</script>

<template>
  <div v-if="version.collaboration || version.featuring || version.producers || version.refs" class="credit-tags">
    <span v-if="version.collaboration" class="credit-tag credit-collab">with {{ version.collaboration }}</span>
    <span v-if="version.featuring" class="credit-tag credit-feat">feat. {{ version.featuring }}</span>
    <span v-if="version.producers" class="credit-tag credit-prod">prod. {{ version.producers }}</span>
    <span v-if="version.refs" class="credit-tag credit-ref">ref. {{ version.refs }}</span>
  </div>
</template>

<style scoped>
.credit-tags {
  font-size: 11px;
  line-height: 1.5;
  text-align: left;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.credit-tag {
  white-space: nowrap;
  background: rgba(255, 255, 255, 0.04);
  padding: 2px 6px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.credit-collab {
  color: var(--text-primary);
}

.credit-feat {
  color: var(--text-primary);
}

.credit-prod {
  color: var(--text-secondary);
}

.credit-ref {
  color: var(--text-dim);
  font-style: italic;
}

@media (max-width: 640px) {
  .credit-tag {
    white-space: normal;
    max-width: 100%;
  }
}
</style>
