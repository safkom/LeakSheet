<script setup>
import { computed } from 'vue'
import { artProxyUrl } from '../composables/usePlayer'
import {
  Dialog,
  DialogScrollContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'

const props = defineProps({
  song: Object,
  version: Object,
  eraArt: String,
  eraName: String,
  artistName: String,
})

const artSrc = computed(() => props.eraArt ? artProxyUrl(props.eraArt) : null)

const emit = defineEmits(['close'])

function handleOpenChange(open) {
  if (!open) emit('close')
}

const v = computed(() => props.version || props.song?.versions?.[0])

const BADGE_LABELS = {
  best: { emoji: '⭐', label: 'Best Of' },
  special: { emoji: '✨', label: 'Special' },
  worst: { emoji: '🗑️', label: 'Worst Of' },
  grail: { emoji: '🏆', label: 'Grail' },
  wanted: { emoji: '🏅', label: 'Wanted' },
}

const badgeInfo = computed(() => {
  const b = v.value?.badge || props.song?.badge
  return b ? BADGE_LABELS[b] || null : null
})

const displayName = computed(() => {
  if (!v.value) return ''
  return v.value.name || props.song?.base_name || 'Unknown'
})

const credits = computed(() => {
  const parts = []
  if (v.value?.collaboration) parts.push({ label: 'with', value: v.value.collaboration })
  if (v.value?.featuring) parts.push({ label: 'feat.', value: v.value.featuring })
  if (v.value?.producers) parts.push({ label: 'prod.', value: v.value.producers })
  if (v.value?.refs) parts.push({ label: 'ref.', value: v.value.refs })
  return parts
})

const details = computed(() => {
  const items = []
  if (v.value?.version_tag) items.push({ label: 'Version', value: v.value.version_tag })
  if (v.value?.quality) items.push({ label: 'Quality', value: v.value.quality })
  if (v.value?.available_length) items.push({ label: 'Available', value: v.value.available_length })
  if (v.value?.track_length) items.push({ label: 'Duration', value: v.value.track_length })
  if (v.value?.file_date) items.push({ label: 'File Date', value: v.value.file_date })
  if (v.value?.leak_date) items.push({ label: 'Leak Date', value: v.value.leak_date })
  if (v.value?.date_of_recording) items.push({ label: 'Recorded', value: v.value.date_of_recording })
  if (v.value?.type) items.push({ label: 'Type', value: v.value.type })
  if (v.value?.og_filename) items.push({ label: 'OG Filename', value: v.value.og_filename })
  return items
})
</script>

<template>
  <Dialog :open="true" @update:open="handleOpenChange">
    <DialogScrollContent class="max-w-[520px] p-0 border-white/10 bg-[hsl(220_24%_12%)] overflow-y-auto rounded-xl">
      <!-- Art Header -->
      <div v-if="artSrc" class="modal-art-header">
        <img :src="artSrc" class="modal-art-img" alt="" />
        <div class="modal-art-overlay"></div>
        <div class="modal-art-info">
          <Badge v-if="badgeInfo" variant="secondary" class="bg-white/15 text-white border-transparent text-[11px] rounded-[4px]">
            {{ badgeInfo.emoji }} {{ badgeInfo.label }}
          </Badge>
          <span v-if="eraName" class="text-xs text-white/70 font-medium">{{ eraName }}</span>
        </div>
      </div>

      <div class="p-6">
        <DialogHeader class="mb-5 !text-left">
          <DialogTitle class="!text-lg !font-bold !leading-tight">{{ displayName }}</DialogTitle>
          <DialogDescription :class="artSrc ? 'sr-only' : 'text-sm text-muted-foreground'">
            {{ eraName || displayName }}
          </DialogDescription>
        </DialogHeader>

        <!-- Credits -->
        <div v-if="credits.length" class="modal-section">
          <div v-for="c in credits" :key="c.label" class="credit-line">
            <span class="credit-label">{{ c.label }}</span>
            <span class="credit-value">{{ c.value }}</span>
          </div>
        </div>

        <!-- Metadata -->
        <div v-if="details.length" class="modal-section">
          <div class="detail-grid">
            <template v-for="d in details" :key="d.label">
              <span class="detail-label">{{ d.label }}</span>
              <span class="detail-value">{{ d.value }}</span>
            </template>
          </div>
        </div>

        <!-- Alt Titles -->
        <div v-if="v?.alt_titles?.length" class="modal-section">
          <div class="section-label">Alternative Titles</div>
          <div v-for="(alt, i) in v.alt_titles" :key="i" class="alt-title">{{ alt }}</div>
        </div>

        <!-- Samples -->
        <div v-if="v?.samples?.length" class="modal-section">
          <div class="section-label">Samples</div>
          <div v-for="(s, i) in v.samples" :key="i" class="sample-item">{{ s }}</div>
        </div>

        <!-- Notes -->
        <div v-if="v?.notes" class="modal-section">
          <div class="section-label">Notes</div>
          <p class="notes-text">{{ v.notes }}</p>
        </div>

        <!-- Links -->
        <div v-if="v?.links?.length" class="modal-section">
          <div class="section-label">Links</div>
          <div v-for="(link, i) in v.links" :key="i" class="link-item">
            <a :href="link" target="_blank" rel="noopener">{{ link }}</a>
          </div>
        </div>
      </div>
    </DialogScrollContent>
  </Dialog>
</template>

<style scoped>
.modal-art-header {
  position: relative;
  height: 140px;
  overflow: hidden;
}

.modal-art-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  filter: brightness(0.5);
}

.modal-art-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(to top, #1a1e26 0%, transparent 70%);
}

.modal-art-info {
  position: absolute;
  bottom: 12px;
  left: 16px;
  right: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.modal-section {
  padding: 12px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.modal-section:first-of-type {
  border-top: none;
  padding-top: 0;
}

.credit-line {
  display: flex;
  gap: 6px;
  font-size: 13px;
  line-height: 1.6;
}

.credit-label {
  color: var(--text-dim);
  font-weight: 500;
}

.credit-value {
  color: var(--text-secondary);
}

.detail-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 16px;
  font-size: 13px;
}

.detail-label {
  color: var(--text-dim);
  font-weight: 500;
}

.detail-value {
  color: var(--text-primary);
}

.section-label {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.alt-title {
  font-size: 13px;
  color: var(--text-secondary);
  font-style: italic;
  line-height: 1.5;
}

.sample-item {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.notes-text {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  white-space: pre-wrap;
}

.link-item a {
  font-size: 12px;
  color: var(--accent-color);
  word-break: break-all;
  line-height: 1.6;
}

.link-item a:hover {
  text-decoration: underline;
}
</style>
