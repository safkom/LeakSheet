<script setup lang="ts">
import { computed, ref, watch, type PropType } from 'vue'
import { BADGE_MAP, qualityVariant, availabilityVariant } from '@/composables/useUtils'
import { fetchMetadata, metadataBadgeVariant, type FileMetadata } from '@/composables/useMetadata'
import { getEraColors } from '@/composables/useEraColors'
import { toast } from 'vue-sonner'
import {
  Dialog,
  DialogScrollContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { Song, SongVersion } from '@/composables/useEraFiltering'

const props = defineProps({
  song: { type: Object as PropType<Song> },
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

const BADGE_LABEL_TEXT: Record<string, string> = { best: 'Best Of', special: 'Special', worst: 'Worst Of', grail: 'Grail', wanted: 'Wanted', ai: 'AI Generated' }
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

const subtitle = computed(() => v.value?.alt_titles?.[0] || null)

const credits = computed(() => {
  const parts: Array<{ label: string; value: string }> = []
  if (v.value?.collaboration) parts.push({ label: 'with', value: v.value.collaboration })
  if (v.value?.featuring) parts.push({ label: 'feat.', value: v.value.featuring })
  if (v.value?.producers) parts.push({ label: 'prod.', value: v.value.producers })
  if (v.value?.refs) parts.push({ label: 'ref.', value: v.value.refs })
  return parts
})

function copyLink(link: string) {
  navigator.clipboard.writeText(link).then(() => {
    toast.success('Link copied')
  }).catch(() => {
    toast.error('Failed to copy')
  })
}

// Quality & availability pulled out as prominent badges
const qualityBadge = computed(() => {
  if (!v.value?.quality) return null
  return { value: v.value.quality, variant: qualityVariant(v.value.quality) }
})
const availBadge = computed(() => {
  if (!v.value?.available_length) return null
  return { value: v.value.available_length, variant: availabilityVariant(v.value.available_length) }
})

// Detail grid — everything except quality/availability (those are now prominent badges)
const details = computed(() => {
  const items: Array<{ label: string; value: string }> = []
  if (v.value?.version_tag) items.push({ label: 'Version', value: v.value.version_tag })
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

// Remaining alt titles (skip first — it's used as subtitle)
const remainingAltTitles = computed(() => {
  const all = v.value?.alt_titles
  if (!all || all.length <= 1) return []
  return all.slice(1)
})

// Collapsible state for Technical Parameters
const techOpen = ref(false)

// Fetch provider metadata
const fileMetadata = ref<FileMetadata | null>(null)
const metadataLoading = ref(false)

const metadataLink = computed(() => v.value?.links?.[0] || null)

watch(metadataLink, async (link) => {
  if (!link) { fileMetadata.value = null; return }
  metadataLoading.value = true
  try {
    fileMetadata.value = await fetchMetadata(link)
  } catch {
    fileMetadata.value = null
  } finally {
    metadataLoading.value = false
  }
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
  if (m.estimated_bitrate) fields.push({ label: 'Est. Bitrate', value: `${Math.round(m.estimated_bitrate)} kbps`, variant: metadataBadgeVariant('estimated_bitrate', m.estimated_bitrate) })
  if (m.duration) {
    const secs = parseFloat(String(m.duration))
    if (!isNaN(secs) && secs > 0) {
      const mins = Math.floor(secs / 60)
      const s = Math.floor(secs % 60)
      fields.push({ label: 'Duration', value: `${mins}:${s.toString().padStart(2, '0')}`, variant: 'secondary' })
    }
  }
  if (m.frequency_cutoff) fields.push({ label: 'Freq. Cutoff', value: `${Math.round(m.frequency_cutoff)} Hz`, variant: 'secondary' })
  if (m.quality_mismatch !== undefined && m.quality_mismatch !== null) {
    fields.push({ label: 'Quality Match', value: m.quality_mismatch ? 'Mismatch' : 'OK', variant: metadataBadgeVariant('quality_mismatch', m.quality_mismatch) })
  }
  return fields
})

const primaryLink = computed(() => v.value?.links?.[0] || null)
const secondaryLinks = computed(() => {
  if (!v.value?.links || v.value.links.length <= 1) return []
  return v.value.links.slice(1)
})

// Era accent colors from ColorThief cache
const eraColors = computed(() => props.eraName ? getEraColors(props.eraName) : null)

// Extract raw RGB from the bg rgba string for blending
const eraRgb = computed(() => {
  const bg = eraColors.value?.bg
  if (!bg) return null
  const m = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
  return m ? { r: +m[1], g: +m[2], b: +m[3] } : null
})

// Stronger tinted background for the entire modal
const modalBg = computed(() => {
  const c = eraRgb.value
  if (!c) return undefined
  return `rgb(${Math.round(c.r * 0.15 + 20)}, ${Math.round(c.g * 0.15 + 22)}, ${Math.round(c.b * 0.15 + 28)})`
})

const cssVars = computed(() => {
  if (!eraColors.value) return {}
  return {
    '--era-accent': eraColors.value.accent,
    '--era-bg': eraColors.value.bg,
    '--era-border': eraColors.value.border,
    '--era-text': eraColors.value.text,
    ...(modalBg.value ? { '--modal-bg': modalBg.value } : {}),
  } as Record<string, string>
})
</script>

<template>
  <Dialog :open="true" @update:open="handleOpenChange">
    <DialogScrollContent
      class="song-desc-modal max-w-[520px] !p-0 !gap-0 border-white/10 overflow-y-auto rounded-xl"
    >
      <div class="modal-shell" :style="cssVars">
      <DialogTitle class="sr-only">{{ displayName }}</DialogTitle>
      <DialogDescription class="sr-only">{{ eraName }}</DialogDescription>

      <!-- Top bar: "Description" center, X right -->
      <div class="top-bar">
        <span class="top-bar-spacer" />
        <span class="top-bar-title">Description</span>
        <button class="top-bar-close" aria-label="Close" @click="emit('close')">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      <!-- Content -->
      <div class="content">
        <!-- Era pill + badge label -->
        <div class="era-header">
          <div v-if="eraName" class="era-pill" :style="eraColors ? { color: eraColors.accent, background: eraColors.bg } : {}">{{ eraName }}</div>
          <span v-if="badgeInfo" class="badge-label-under-era">{{ badgeInfo.label }}</span>
        </div>

        <!-- Title -->
        <div class="title-row">
          <span v-if="badgeInfo" class="badge-emoji" aria-hidden="true">{{ badgeInfo.emoji }}</span>
          <h2 class="song-title">{{ displayName }}</h2>
        </div>

        <!-- Subtitle (first alt title) -->
        <p v-if="subtitle" class="song-subtitle">{{ subtitle }}</p>

        <!-- Credits -->
        <div v-if="credits.length" class="credits">
          <div v-for="c in credits" :key="c.label" class="credit-line">
            <span class="credit-label">{{ c.label }}</span>
            <span class="credit-value">{{ c.value }}</span>
          </div>
        </div>

        <!-- Prominent status badges -->
        <div v-if="qualityBadge || availBadge" class="status-badges">
          <Badge v-if="qualityBadge" :variant="qualityBadge.variant" class="status-pill">{{ qualityBadge.value }}</Badge>
          <Badge v-if="availBadge" :variant="availBadge.variant" class="status-pill">{{ availBadge.value }}</Badge>
        </div>

        <!-- Detail grid -->
        <div v-if="details.length" class="section">
          <div class="detail-grid">
            <template v-for="d in details" :key="d.label">
              <span class="detail-label">{{ d.label }}</span>
              <span class="detail-value">{{ d.value }}</span>
            </template>
          </div>
        </div>

        <!-- Technical Parameters (collapsible card) -->
        <div v-if="metadataFields.length || metadataLoading" class="section">
          <Collapsible v-model:open="techOpen">
            <div class="tech-card">
              <CollapsibleTrigger class="tech-trigger">
                <span class="section-label-inline">Technical Parameters</span>
                <svg :class="['chevron', { open: techOpen }]" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div v-if="metadataLoading" class="metadata-loading">Fetching file info...</div>
                <div v-else class="detail-grid tech-grid">
                  <template v-for="f in metadataFields" :key="f.label">
                    <span class="detail-label">{{ f.label }}</span>
                    <Badge :variant="f.variant" class="self-center justify-self-start">{{ f.value }}</Badge>
                  </template>
                </div>
              </CollapsibleContent>
            </div>
          </Collapsible>
        </div>

        <!-- Remaining Alt Titles -->
        <div v-if="remainingAltTitles.length" class="section">
          <div class="section-label">Alternative Titles</div>
          <div v-for="(alt, i) in remainingAltTitles" :key="'alt_' + i + '_' + alt" class="alt-title">{{ alt }}</div>
        </div>

        <!-- Samples -->
        <div v-if="v?.samples?.length" class="section">
          <div class="section-label">Samples</div>
          <div v-for="(s, i) in v.samples" :key="'sample_' + i + '_' + s" class="sample-item">{{ s }}</div>
        </div>

        <!-- Notes (card container) -->
        <div v-if="cleanedNotes" class="section">
          <div class="section-label">Notes</div>
          <div class="notes-card">
            <p class="notes-text">{{ cleanedNotes }}</p>
          </div>
        </div>

        <!-- Secondary links (if multiple) -->
        <div v-if="secondaryLinks.length" class="section">
          <div class="section-label">Additional Links</div>
          <div v-for="(link, i) in secondaryLinks" :key="'link_' + i + '_' + link" class="link-item">
            <a :href="link" target="_blank" rel="noopener">{{ link }}</a>
            <button class="link-copy-btn" @click.prevent="copyLink(link)" aria-label="Copy link">
              <svg viewBox="0 0 16 16" width="13" height="13">
                <path fill="currentColor" d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25ZM5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- Download button (always last) -->
        <div v-if="primaryLink" class="download-area">
          <a :href="primaryLink" target="_blank" rel="noopener" class="download-btn">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Download
          </a>
        </div>
      </div>
      </div>
    </DialogScrollContent>
  </Dialog>
</template>

<style scoped>
/* ── Modal shell (carries bg + CSS vars) ───── */
.modal-shell {
  background: var(--modal-bg, hsl(220 24% 12%));
  border-radius: 12px;
  min-height: 100%;
}

/* ── Top bar ─────────────────────────────────── */
.top-bar {
  display: flex;
  align-items: center;
  padding: 16px 20px;
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--modal-bg, hsl(220 24% 12%));
  border-bottom: 1px solid var(--era-border, rgba(255, 255, 255, 0.06));
}

.top-bar-close {
  flex-shrink: 0;
  color: var(--text-dim);
  padding: 4px;
  border-radius: 6px;
  transition: color 0.15s, background 0.15s;
}

.top-bar-close:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.08);
}

.top-bar-title {
  flex: 1;
  text-align: center;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.2px;
}

.top-bar-spacer {
  width: 26px;
  flex-shrink: 0;
}

/* ── Content ─────────────────────────────────── */
.content {
  padding: 20px 24px 24px;
}

/* ── Era header (pill + badge label) ──────────── */
.era-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.era-pill {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--era-accent, hsl(230 80% 68%));
  background: rgba(255, 255, 255, 0.08);
  padding: 5px 14px;
  border-radius: 20px;
}

.badge-label-under-era {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  color: var(--text-dim);
}

/* ── Title ───────────────────────────────────── */
.title-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.badge-emoji {
  font-size: 24px;
  line-height: 1;
  flex-shrink: 0;
}

.song-title {
  font-size: 28px;
  font-weight: 800;
  line-height: 1.15;
  color: var(--era-accent, hsl(230 80% 68%));
  margin: 0;
}

.song-subtitle {
  font-size: 15px;
  color: var(--text-dim);
  margin: 6px 0 0;
  font-style: italic;
  line-height: 1.4;
}

/* ── Credits ─────────────────────────────────── */
.credits {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.credit-line {
  font-size: 14px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.credit-label {
  font-weight: 700;
  text-transform: uppercase;
  font-size: 12px;
  letter-spacing: 0.3px;
  color: var(--era-accent, var(--text-primary));
  margin-right: 4px;
}

.credit-value {
  color: var(--text-secondary);
}

/* ── Status badges ───────────────────────────── */
.status-badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
}

.status-pill {
  font-size: 12px;
  font-weight: 600;
  padding: 5px 14px;
}



/* ── Sections ────────────────────────────────── */
.section {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--era-border, rgba(255, 255, 255, 0.06));
}

/* ── Detail grid ─────────────────────────────── */
.detail-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px 20px;
  font-size: 14px;
}

.detail-label {
  color: var(--era-accent, var(--text-dim));
  font-weight: 500;
  opacity: 0.7;
}

.detail-value {
  color: var(--text-primary);
  overflow-wrap: anywhere;
  word-break: break-all;
  min-width: 0;
}

/* ── Technical Parameters (collapsible card) ─── */
.tech-card {
  border: 1px solid var(--era-border, rgba(255, 255, 255, 0.08));
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--era-bg, rgba(255, 255, 255, 0.02));
}

.tech-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 0;
  color: var(--text-dim);
  cursor: pointer;
  background: none;
  border: none;
}

.section-label-inline {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--era-accent, var(--text-dim));
  opacity: 0.7;
}

.chevron {
  transition: transform 0.2s ease;
  color: var(--text-dim);
}

.chevron.open {
  transform: rotate(180deg);
}

.tech-grid {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

/* ── Section labels ──────────────────────────── */
.section-label {
  color: var(--era-accent, var(--text-dim));
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  margin-bottom: 10px;
  opacity: 0.7;
}

.alt-title {
  font-size: 14px;
  color: var(--text-secondary);
  font-style: italic;
  line-height: 1.5;
}

.sample-item {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* ── Notes card ──────────────────────────────── */
.notes-card {
  background: var(--era-bg, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--era-border, rgba(255, 255, 255, 0.06));
  border-radius: 12px;
  padding: 16px;
}

/* ── Link accent color ───────────────────────── */
.link-item a {
  color: var(--era-accent, var(--accent-color));
}

.notes-text {
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
  margin: 0;
}

/* ── Links ───────────────────────────────────── */
.link-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.link-item a {
  flex: 1;
  font-size: 13px;
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

/* ── Download ────────────────────────────────── */
.download-area {
  margin-top: 24px;
}

.download-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 14px 0;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 600;
  color: var(--era-text, var(--text-primary));
  background: var(--era-bg, rgba(255, 255, 255, 0.08));
  border: 1px solid var(--era-border, rgba(255, 255, 255, 0.06));
  transition: background 0.15s, border-color 0.15s;
  text-decoration: none;
}

.download-btn:hover {
  background: rgba(255, 255, 255, 0.14);
}

/* ── Metadata loading ────────────────────────── */
.metadata-loading {
  font-size: 13px;
  color: var(--text-dim);
  font-style: italic;
  margin-top: 10px;
}
</style>

<!-- Non-scoped: hide the built-in DialogClose in portaled dialog -->
<style>
.song-desc-modal > button:last-child {
  display: none !important;
}
</style>
