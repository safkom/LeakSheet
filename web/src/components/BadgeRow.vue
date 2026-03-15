<script setup lang="ts">
import { computed, type PropType } from 'vue'
import { Badge } from '@/components/ui/badge'
import { effectiveBadge, getAvailBadge, coloredBadgeStyle } from '../composables/useUtils'
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

const qualityStyle = computed(() => coloredBadgeStyle(props.version.quality_color))
const availStyle = computed(() => coloredBadgeStyle(props.version.available_length_color))
</script>

<template>
  <Badge
    v-if="badge"
    :variant="qualityStyle ? undefined : badge.variant"
    :style="qualityStyle"
  >{{ badge.text }}</Badge>
  <Badge
    v-if="availBadge"
    :variant="availStyle ? undefined : availBadge.variant"
    :style="availStyle"
  >{{ availBadge.text }}</Badge>
</template>
