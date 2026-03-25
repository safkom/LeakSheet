<script setup lang="ts">
import { computed, ref, onUnmounted, type PropType } from 'vue'
import { extractAndCacheEraColors, setEraColors, getColorThief } from '../composables/useEraColors'
import { enhanceGoogleImageUrl } from '../composables/usePlayer'
import type { Era } from '../composables/useEraFiltering'

const props = defineProps({
  era: { type: Object as PropType<Era>, required: true },
  expanded: Boolean,
  index: { type: Number, default: 0 },
  sticky: Boolean,
  bestOf: { type: Boolean, default: false },
})

const emit = defineEmits(['click'])

const gradientStyle = ref({})
const titleColor = ref('#e6edf3')
const colorsReady = ref(false)
const imgRetries = ref(0)
const descOpen = ref(false)
const MAX_RETRIES = 2
let _retryTimer = null

onUnmounted(() => {
  if (_retryTimer) clearTimeout(_retryTimer)
})

const artSrc = computed(() => {
  if (!props.era.art_url) return null
  const url = props.era.art_url
  let fullUrl = url.startsWith('//') ? 'https:' + url : url
  if (fullUrl.startsWith('http')) {
    fullUrl = enhanceGoogleImageUrl(fullUrl)
    return `/api/image-proxy?url=${encodeURIComponent(fullUrl)}`
  }
  return url
})

function extractColors(imgElement) {
  if (!imgElement || colorsReady.value) return
  try {
    const ct = getColorThief()
    const pal = ct.getPalette(imgElement, 5)

    if (pal && pal.length >= 2) {
      const c1 = pal[0]
      const c2 = pal[1]
      const d1 = `rgba(${Math.floor(c1[0] * 0.55)}, ${Math.floor(c1[1] * 0.55)}, ${Math.floor(c1[2] * 0.55)}, 0.95)`
      const d2 = `rgba(${Math.floor(c2[0] * 0.4)}, ${Math.floor(c2[1] * 0.4)}, ${Math.floor(c2[2] * 0.4)}, 0.9)`
      const bright = `rgb(${Math.min(255, c1[0] + 60)}, ${Math.min(255, c1[1] + 60)}, ${Math.min(255, c1[2] + 60)})`

      gradientStyle.value = {
        background: `linear-gradient(135deg, ${d1}, ${d2})`,
        borderColor: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.3)`,
      }
      titleColor.value = bright

      // Share colors for search result badges + player accent
      setEraColors(props.era.name, {
        bg: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.2)`,
        text: bright,
        border: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.3)`,
        accent: bright,
      })
    }
    colorsReady.value = true
  } catch (e) {
    colorsReady.value = true
  }
}

function onImgLoad(e) {
  const img = e.target
  extractColors(img)
}

function onImgError(e) {
  if (e.target && imgRetries.value < MAX_RETRIES) {
    imgRetries.value++
    _retryTimer = setTimeout(() => {
      if (e.target && artSrc.value) {
        const sep = artSrc.value.includes('?') ? '&' : '?'
        e.target.src = `${artSrc.value}${sep}_r=${imgRetries.value}`
      }
    }, 500 * imgRetries.value)
    return
  }
  if (e.target) {
    e.target.style.display = 'none'
    const wrapper = e.target.parentElement
    if (wrapper) {
      wrapper.classList.add('img-error')
    }
  }
}

// Stagger animation delay based on index
const animDelay = computed(() => `${Math.min(props.index * 50, 300)}ms`)
</script>

<template>
  <div
    class="era-card-wrapper"
    :class="{ expanded, 'has-colors': colorsReady, 'era-sticky': sticky }"
    :style="{ '--stagger': animDelay }"
  >
    <!-- Main clickable card -->
    <button
      class="era-card"
      :class="{ expanded, 'best-of-active': bestOf }"
      :style="gradientStyle"
      :aria-expanded="expanded"
      @click="emit('click')"
    >
      <!-- Single unified layout -->
      <div class="era-layout">
        <!-- Art: responsive sizing via CSS -->
        <div class="era-art" v-if="artSrc">
          <img
            :src="artSrc"
            alt=""
            :loading="index < 6 ? 'eager' : 'lazy'"
            crossorigin="anonymous"
            @load="onImgLoad"
            @error="onImgError"
            class="era-art-img"
          />
          <div class="era-art-fallback">
            <svg viewBox="0 0 24 24" width="28" height="28">
              <path fill="currentColor" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55C7.79 13 6 14.79 6 17s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
            </svg>
          </div>
        </div>
        <div class="era-art era-art-empty" v-else>
          <svg viewBox="0 0 24 24" width="28" height="28">
            <path fill="currentColor" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55C7.79 13 6 14.79 6 17s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
          </svg>
        </div>

        <!-- Info -->
        <div class="era-info">
          <h3 class="era-title" :style="{ color: titleColor }">{{ era.name }}</h3>
          <div v-if="era.alt_names?.length" class="era-alt-names">{{ era.alt_names.join(', ') }}</div>

          <!-- Desktop-only timeline -->
          <div v-if="era.timeline?.length" class="era-timeline">
            <div v-for="(evt, i) in era.timeline.slice(0, 4)" :key="i" class="timeline-evt">
              <span class="timeline-date">{{ evt.date }}</span>
              <span class="timeline-sep">&mdash;</span>
              <span class="timeline-text">{{ evt.event }}</span>
            </div>
          </div>
        </div>
      </div>
    </button>

    <!-- Description row — shown below the main card button if era has a description.
         Separate element so we can use a proper <button> for the toggle without
         nesting interactive elements. -->
    <div v-if="era.description" class="era-desc-row">
      <button
        class="era-desc-toggle"
        :aria-expanded="descOpen"
        @click.stop="descOpen = !descOpen"
      >
        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
          <path fill="currentColor" d="M0 1.75A.75.75 0 0 1 .75 1h4.253c1.227 0 2.317.59 3 1.501A3.744 3.744 0 0 1 11.006 1h4.245a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75h-4.507a2.25 2.25 0 0 0-1.591.659l-.622.621a.75.75 0 0 1-1.06 0l-.622-.621A2.25 2.25 0 0 0 5.258 13H.75a.75.75 0 0 1-.75-.75zm7.251 10.324l.004-5.073-.002-2.253A2.25 2.25 0 0 0 5.003 2.5H1.5v9h3.757a3.75 3.75 0 0 1 1.994.574zM8.755 4.75l-.004 7.322a3.752 3.752 0 0 1 1.992-.572H14.5v-9h-3.495a2.25 2.25 0 0 0-2.25 2.25z"/>
        </svg>
        <span>{{ descOpen ? 'Hide description' : 'Description' }}</span>
        <svg class="desc-chevron" :class="{ 'desc-chevron-open': descOpen }" viewBox="0 0 16 16" width="10" height="10" aria-hidden="true">
          <path fill="currentColor" d="M4.427 7.427l3.396 3.396a.25.25 0 0 0 .354 0l3.396-3.396A.25.25 0 0 0 11.396 7H4.604a.25.25 0 0 0-.177.427z"/>
        </svg>
      </button>
      <Transition name="desc-expand">
        <div v-if="descOpen" class="era-desc-wrap">
          <p class="era-desc-content">{{ era.description }}</p>
        </div>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
/* ── Wrapper — holds card button + optional description row ── */
.era-card-wrapper {
  display: flex;
  flex-direction: column;
}

.era-card {
  width: 100%;
  position: relative;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 0;
  text-align: left;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
  cursor: pointer;
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.03) inset;
  /* Stagger entry animation */
  animation: era-enter 0.35s ease both;
  animation-delay: var(--stagger, 0ms);
}

@keyframes era-enter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.era-card:hover {
  border-color: rgba(255, 255, 255, 0.18);
  transform: translateY(-1px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
}

.era-card.expanded {
  border-radius: 12px 12px 0 0;
  transform: none;
  box-shadow: none;
}

/* ── Single layout: responsive art + info ── */
.era-layout {
  display: flex;
  align-items: center;
  padding: 14px 16px;
  gap: 14px;
}

/* Art — responsive sizing */
.era-art {
  width: 64px;
  height: 64px;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  flex-shrink: 0;
  position: relative;
}

.era-art-empty {
  background: rgba(255, 255, 255, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
}

.era-art-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.era-art-fallback {
  display: none;
  width: 100%;
  height: 100%;
  background: rgba(255, 255, 255, 0.05);
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
}

.img-error .era-art-img {
  display: none;
}

.img-error .era-art-fallback {
  display: flex;
}

/* Info */
.era-info {
  flex: 1;
  min-width: 0;
}

.era-title {
  font-size: 16px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.3px;
  transition: color 0.3s;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.era-alt-names {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Timeline: hidden on mobile */
.era-timeline {
  display: none;
}

/* ── Desktop (768px+) ── */
@media (min-width: 768px) {
  .era-layout {
    align-items: flex-start;
    gap: 20px;
    padding: 16px 20px;
  }

  .era-art {
    width: 88px;
    height: 88px;
    border-radius: 10px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  }

  .era-title {
    font-size: 20px;
    margin-bottom: 2px;
  }

  .era-alt-names {
    font-size: 12px;
    margin-bottom: 6px;
  }

  .era-timeline {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-bottom: 8px;
  }

  .timeline-evt {
    font-size: 11px;
    line-height: 1.4;
    display: flex;
    gap: 4px;
    overflow: hidden;
  }

  .timeline-date {
    color: rgba(255, 255, 255, 0.7);
    font-weight: 600;
    flex-shrink: 0;
  }

  .timeline-sep {
    color: rgba(255, 255, 255, 0.2);
    flex-shrink: 0;
  }

  .timeline-text {
    color: rgba(255, 255, 255, 0.45);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

/* ── Description row ── */
.era-desc-row {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-color);
  border-top: none;
  border-radius: 0 0 12px 12px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.02);
}

.era-card.expanded + .era-desc-row {
  border-color: rgba(255, 255, 255, 0.12);
  border-radius: 0;
}

.era-desc-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  cursor: pointer;
  color: rgba(255, 255, 255, 0.4);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.3px;
  transition: color 0.15s;
}

.era-desc-toggle:hover {
  color: rgba(255, 255, 255, 0.7);
}

.desc-chevron {
  margin-left: auto;
  transition: transform 0.2s ease;
  opacity: 0.6;
}

.desc-chevron-open {
  transform: rotate(180deg);
}

.era-desc-content {
  color: rgba(255, 255, 255, 0.6);
  font-size: 12px;
  line-height: 1.6;
  padding: 0 14px 12px;
  margin: 0;
  white-space: pre-wrap;
}

/* Smooth expand/collapse transition — grid technique */
.era-desc-wrap {
  display: grid;
  grid-template-rows: 1fr;
}

.era-desc-wrap .era-desc-content {
  overflow: hidden;
  min-height: 0;
}

.desc-expand-enter-active,
.desc-expand-leave-active {
  transition: grid-template-rows 0.25s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.2s ease;
}

.desc-expand-enter-from,
.desc-expand-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
}

.desc-expand-enter-to,
.desc-expand-leave-from {
  grid-template-rows: 1fr;
  opacity: 1;
}

/* ── Sticky state (all sizes) ── */
.era-card-wrapper.era-sticky .era-card {
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  animation: none;
}

.era-card-wrapper.era-sticky .era-card .era-layout {
  padding: 8px 16px;
  gap: 10px;
  align-items: center;
}

.era-card-wrapper.era-sticky .era-card .era-art {
  width: 32px;
  height: 32px;
  border-radius: 4px;
}

.era-card-wrapper.era-sticky .era-card .era-art svg {
  width: 16px;
  height: 16px;
}

.era-card-wrapper.era-sticky .era-card .era-title {
  font-size: 14px;
  -webkit-line-clamp: 1;
  margin-bottom: 0;
}

.era-card-wrapper.era-sticky .era-card .era-alt-names,
.era-card-wrapper.era-sticky .era-card .era-timeline {
  display: none;
}

.era-card-wrapper.era-sticky .era-desc-row {
  display: none;
}

/* Mobile sizing boost */
@media (max-width: 767px) {
  .era-layout { padding: 12px 14px; gap: 12px; }
  .era-art { width: 56px; height: 56px; }
  .era-title { font-size: 15px; }
  .era-alt-names { font-size: 11px; }
  .era-desc-content { font-size: 13px; }
  .era-desc-toggle { font-size: 12px; padding: 8px 14px; }
}

/* Mobile sticky: remove horizontal borders */
@media (max-width: 767px) {
  .era-card-wrapper.era-sticky .era-card {
    border-radius: 0;
    border-left: none;
    border-right: none;
  }
}

/* Desktop sticky: rounded top corners */
@media (min-width: 768px) {
  .era-card-wrapper.era-sticky .era-card {
    border-radius: 6px 6px 0 0;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
  }

  .era-card-wrapper.era-sticky .era-card .era-layout {
    padding: 10px 16px;
    gap: 12px;
  }

  .era-card-wrapper.era-sticky .era-card .era-art {
    width: 40px;
    height: 40px;
  }

  .era-card-wrapper.era-sticky .era-card .era-title {
    font-size: 15px;
  }
}

/* Best-of mode: era clicking is disabled */
.era-card.best-of-active {
  cursor: default;
}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  .era-card {
    animation: none;
  }
}
</style>
