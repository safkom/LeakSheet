<script setup lang="ts">
import { computed, ref, watch, type PropType } from 'vue'
import { BADGE_MAP, qualityVariant, availabilityVariant } from '@/composables/useUtils'
import { fetchMetadata, metadataBadgeVariant, type FileMetadata } from '@/composables/useMetadata'
import { toast } from 'vue-sonner'
import {
  Dialog,
  DialogScrollContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import type { Song, SongVersion } from '@/composables/useEraFiltering'

const props = defineProps({
  song: { type: Object as PropType<Song>, required: true },
  version: { type: Object as PropType<SongVersion> },
  eraArt: String,
  eraName: String,
  artistName: String,
})

const emit = defineEmits(['close'])

function handleOpenChange(open: boolean) {
  if (!open) emit('close')
}

const v = computed(() => props.version || props.song?.versions?.[0])

const BADGE_LABEL_TEXT = { best: 'Best Of', special: 'Special', worst: 'Worst Of', grail: 'Grail', wanted: 'Wanted', ai: 'AI Generated' }
const BADGE_LABELS = Object.fromEntries(
  Object.entries(BADGE_MAP).map(([k, emoji]) => [k, { emoji, label: BADGE_LABEL_TEXT[k] }])
)

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

function copyLink(link) {
  navigator.clipboard.writeText(link).then(() => {
    toast.success('Link copied')
  }).catch(() => {
    toast.error('Failed to copy')
  })
}

const details = computed(() => {
  const items = []
  if (v.value?.version_tag) items.push({ label: 'Version', value: v.value.version_tag })
  if (v.value?.quality) {
    items.push({ label: 'Quality', value: v.value.quality, badgeVariant: qualityVariant(v.value.quality) })
  }
  if (v.value?.available_length) {
    items.push({ label: 'Available', value: v.value.available_length, badgeVariant: availabilityVariant(v.value.available_length) })
  }
  if (v.value?.track_length) items.push({ label: 'Duration', value: v.value.track_length })
  if (v.value?.file_date) items.push({ label: 'File Date', value: v.value.file_date })
  if (v.value?.leak_date) items.push({ label: 'Leak Date', value: v.value.leak_date })
  if (v.value?.date_of_recording) items.push({ label: 'Recorded', value: v.value.date_of_recording })
  if (v.value?.type) items.push({ label: 'Type', value: v.value.type })
  if (v.value?.og_filename) items.push({ label: 'OG Filename', value: v.value.og_filename })
  return items
})

/** Strip duplicate OG filename lines from notes since it's already shown in the details grid. */
const cleanedNotes = computed(() => {
  const raw = v.value?.notes
  if (!raw) return ''
  return raw
    .split('\n')
    .filter(line => !/^og\s*filename\s*:/i.test(line.trim()))
    .join('\n')
    .trim()
})

// Fetch provider metadata
const fileMetadata = ref<FileMetadata | null>(null)
const metadataLoading = ref(false)

const metadataLink = computed(() => v.value?.links?.[0] || null)

watch(metadataLink, async (link) => {
  if (!link) { fileMetadata.value = null; return }
  metadataLoading.value = true
  fileMetadata.value = await fetchMetadata(link)
  metadataLoading.value = false
}, { immediate: true })

const metadataFields = computed(() => {
  const m = fileMetadata.value
  if (!m) return []
  const fields: Array<{ label: string; value: string; variant: string }> = []
  if (m.container) fields.push({ label: 'Container', value: m.container, variant: 'secondary' })
  if (m.codec) fields.push({ label: 'Codec', value: m.codec, variant: 'secondary' })
  if (m.codec_profile) fields.push({ label: 'Profile', value: m.codec_profile, variant: 'secondary' })
  if (m.bitrate) fields.push({ label: 'Bitrate', value: m.bitrate, variant: metadataBadgeVariant('bitrate', m.bitrate) })
  if (m.sample_rate) fields.push({ label: 'Sample Rate', value: m.sample_rate, variant: 'secondary' })
  if (m.bits_per_sample) fields.push({ label: 'Bit Depth', value: m.bits_per_sample, variant: 'secondary' })
  if (m.lossless !== undefined && m.lossless !== null) {
    fields.push({ label: 'Lossless', value: m.lossless ? 'Yes' : 'No', variant: metadataBadgeVariant('lossless', m.lossless) })
  }
  if (m.channels) fields.push({ label: 'Channels', value: String(m.channels), variant: 'secondary' })
  if (m.estimated_bitrate) fields.push({ label: 'Est. Bitrate', value: `${m.estimated_bitrate} kbps`, variant: metadataBadgeVariant('estimated_bitrate', m.estimated_bitrate) })
  if (m.frequency_cutoff) fields.push({ label: 'Freq. Cutoff', value: `${Math.round(m.frequency_cutoff)} Hz`, variant: 'secondary' })
  if (m.quality_mismatch !== undefined && m.quality_mismatch !== null) {
    fields.push({ label: 'Quality Match', value: m.quality_mismatch ? 'Mismatch' : 'OK', variant: metadataBadgeVariant('quality_mismatch', m.quality_mismatch) })
  }
  return fields
})
</script>

<template>
  <Dialog :open="true" @update:open="handleOpenChange">
    <DialogScrollContent class="max-w-[520px] p-0 border-white/10 bg-[hsl(220_24%_12%)] overflow-y-auto rounded-xl">
      <!-- Accessible title (visually hidden fallback) -->
      <DialogTitle class="sr-only">{{ displayName }}</DialogTitle>
      <DialogDescription class="sr-only">{{ eraName }}</DialogDescription>

      <!-- Header -->
      <div class="modal-header">
        <div class="modal-title-row">
          <span v-if="badgeInfo" class="modal-badge-emoji" aria-hidden="true">{{ badgeInfo.emoji }}</span>
          <h2 class="modal-title">{{ displayName }}</h2>
        </div>
        <div v-if="eraName || badgeInfo" class="modal-meta-row">
          <span v-if="eraName" class="modal-era-pill">{{ eraName }}</span>
          <span v-if="badgeInfo" class="modal-badge-label">{{ badgeInfo.label }}</span>
        </div>
      </div>

      <div class="p-5">
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
              <Badge v-if="d.badgeVariant" :variant="d.badgeVariant" class="self-center justify-self-start">{{ d.value }}</Badge>
              <span v-else class="detail-value">{{ d.value }}</span>
            </template>
          </div>
        </div>

        <!-- File Info (fetched from provider) -->
        <div v-if="metadataFields.length || metadataLoading" class="modal-section">
          <div class="section-label">File Info</div>
          <div v-if="metadataLoading" class="metadata-loading">Fetching...</div>
          <div v-else class="detail-grid">
            <template v-for="f in metadataFields" :key="f.label">
              <span class="detail-label">{{ f.label }}</span>
              <Badge :variant="f.variant" class="self-center justify-self-start">{{ f.value }}</Badge>
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
        <div v-if="cleanedNotes" class="modal-section">
          <div class="section-label">Notes</div>
          <p class="notes-text">{{ cleanedNotes }}</p>
        </div>

        <!-- Links -->
        <div v-if="v?.links?.length" class="modal-section">
          <div class="section-label">Links</div>
          <div v-for="(link, i) in v.links" :key="i" class="link-item">
            <a :href="link" target="_blank" rel="noopener">{{ link }}</a>
            <button class="link-copy-btn" @click.prevent="copyLink(link)" aria-label="Copy link">
              <svg viewBox="0 0 16 16" width="13" height="13">
                <path fill="currentColor" d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25ZM5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </DialogScrollContent>
  </Dialog>
</template>

<style scoped>
.modal-header {
  padding: 22px 24px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}

.modal-title-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}

.modal-badge-emoji {
  font-size: 18px;
  line-height: 1;
  flex-shrink: 0;
}

.modal-title {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.25;
  color: var(--text-primary);
  margin: 0;
}

.modal-meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.modal-era-pill {
  font-size: 12px;
  color: var(--text-dim);
  background: rgba(255, 255, 255, 0.07);
  padding: 2px 9px;
  border-radius: 20px;
  letter-spacing: 0.1px;
}

.modal-badge-label {
  font-size: 11px;
  color: var(--text-dim);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.4px;
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
  gap: 5px 16px;
  font-size: 13px;
}

.detail-label {
  color: var(--text-dim);
  font-weight: 500;
}

.detail-value {
  color: var(--text-primary);
  overflow-wrap: anywhere;
  word-break: break-all;
  min-width: 0;
}

.section-label {
  color: var(--text-dim);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.6px;
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

.link-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.link-item a {
  flex: 1;
  font-size: 12px;
  color: var(--accent-color);
  word-break: break-all;
  line-height: 1.6;
}

.link-item a:hover {
  text-decoration: underline;
}

.link-copy-btn {
  flex-shrink: 0;
  color: var(--text-dim);
  padding: 2px;
  border-radius: 4px;
  opacity: 0.6;
  transition: opacity 0.15s, color 0.15s;
  margin-top: 2px;
}

.link-copy-btn:hover {
  opacity: 1;
  color: var(--text-primary);
}

.metadata-loading {
  font-size: 12px;
  color: var(--text-dim);
  font-style: italic;
}
</style>
