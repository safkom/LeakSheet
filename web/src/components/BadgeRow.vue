<script setup lang="ts">
import { computed, type PropType } from 'vue'
import { Badge } from '@/components/ui/badge'
import { effectiveBadge, getAvailBadge } from '../composables/useUtils'
import type { SongVersion } from '../composables/useEraFiltering'

const props = defineProps({
  version: { type: Object as PropType<SongVersion>, required: true },
})

const badge = computed(() => {
  return effectiveBadge(props.version.quality, props.version.available_length)
})

const availBadge = computed(() => {
  return getAvailBadge(props.version.quality, props.version.available_length)
})
</script>

<template>
  <span v-if="badge || availBadge" class="badge-row">
    <Badge
      v-if="badge"
      :variant="badge.variant"
    >{{ badge.text }}</Badge>
    <Badge
      v-if="availBadge"
      :variant="availBadge.variant"
    >{{ availBadge.text }}</Badge>
  </span>
</template>

<style scoped>
.badge-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
}
</style>
