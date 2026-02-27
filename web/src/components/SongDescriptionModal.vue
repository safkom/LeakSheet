<script setup>
import { computed } from 'vue'
import { artProxyUrl } from '../composables/usePlayer.js'

const props = defineProps({
  song: Object,
  version: Object,
  eraArt: String,
  eraName: String,
  artistName: String,
})

const artSrc = computed(() => props.eraArt ? artProxyUrl(props.eraArt) : null)

const emit = defineEmits(['close'])

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
  <Teleport to="body">
    <div class="modal-backdrop" @click="emit('close')">
      <div class="modal-content" @click.stop>
        <!-- Art Header -->
        <div v-if="artSrc" class="modal-art-header">
          <img :src="artSrc" class="modal-art-img" alt="" />
          <div class="modal-art-overlay"></div>
          <div class="modal-art-info">
            <span v-if="badgeInfo" class="modal-badge">{{ badgeInfo.emoji }} {{ badgeInfo.label }}</span>
            <span v-if="eraName" class="modal-era-label">{{ eraName }}</span>
          </div>
        </div>

        <div class="modal-body">
        <div class="modal-header">
          <h3 class="modal-title">{{ displayName }}</h3>
          <button class="modal-close" @click="emit('close')">
            <svg viewBox="0 0 16 16" width="16" height="16">
              <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
            </svg>
          </button>
        </div>

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
        </div><!-- .modal-body -->
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fade-in 0.15s ease;
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-content {
  background: #1a1e26;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  max-width: 520px;
  width: 100%;
  max-height: 80vh;
  overflow-y: auto;
  animation: modal-in 0.2s ease;
}

.modal-art-header {
  position: relative;
  height: 140px;
  overflow: hidden;
  border-radius: 12px 12px 0 0;
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

.modal-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
}

.modal-era-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  font-weight: 500;
}

.modal-body {
  padding: 24px;
}

@keyframes modal-in {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(10px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.modal-title {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.3;
}

.modal-close {
  flex-shrink: 0;
  color: var(--text-dim);
  padding: 4px;
  border-radius: 6px;
  transition: all 0.1s;
}

.modal-close:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.1);
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
  color: var(--accent);
  word-break: break-all;
  line-height: 1.6;
}

.link-item a:hover {
  text-decoration: underline;
}
</style>
