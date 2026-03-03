<script setup>
import { computed, ref } from 'vue'
import ColorThief from 'colorthief'
import { setEraColors } from '../composables/useEraColors'

const props = defineProps({
  era: Object,
  expanded: Boolean,
  index: { type: Number, default: 0 },
  sticky: Boolean,
})

const emit = defineEmits(['click'])

const gradientStyle = ref({})
const titleColor = ref('#e6edf3')
// Singleton ColorThief — stateless utility, no need to instantiate per component
let _colorThief = null
function getColorThief() {
  if (!_colorThief) _colorThief = new ColorThief()
  return _colorThief
}
const colorsReady = ref(false)
const imgRetries = ref(0)
const MAX_RETRIES = 2

const artSrc = computed(() => {
  if (!props.era.art_url) return null
  const url = props.era.art_url
  const fullUrl = url.startsWith('//') ? 'https:' + url : url
  if (fullUrl.startsWith('http')) {
    return `/api/image-proxy?url=${encodeURIComponent(fullUrl)}`
  }
  return url
})

function extractColors(imgElement) {
  if (!imgElement || colorsReady.value) return
  try {
    const ct = getColorThief()
    const dom = ct.getColor(imgElement)
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

      // Share colors for search result badges
      setEraColors(props.era.name, {
        bg: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.2)`,
        text: bright,
        border: `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, 0.3)`,
      })
    }
    colorsReady.value = true
  } catch (e) {
    colorsReady.value = true
  }
}

function onImgLoad(e) {
  const img = e.target
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(() => extractColors(img), { timeout: 2000 })
  } else {
    setTimeout(() => extractColors(img), 100)
  }
}

function onImgError(e) {
  if (e.target && imgRetries.value < MAX_RETRIES) {
    imgRetries.value++
    setTimeout(() => {
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
  <button
    class="era-card"
    :class="{ expanded, 'has-colors': colorsReady, 'era-sticky': sticky }"
    :style="{ ...gradientStyle, '--stagger': animDelay }"
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

        <!-- Desktop-only extras -->
        <p v-if="era.description" class="era-desc">{{ era.description }}</p>
        <div v-if="era.timeline?.length" class="era-timeline">
          <div v-for="(evt, i) in era.timeline.slice(0, 4)" :key="i" class="timeline-evt">
            <span class="timeline-date">{{ evt.date }}</span>
            <span class="timeline-sep">&mdash;</span>
            <span class="timeline-text">{{ evt.event }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Expand indicator -->
    <div class="era-expand-indicator">
      <svg viewBox="0 0 16 16" width="14" height="14" :class="{ rotated: expanded }">
        <path fill="currentColor" d="M4.427 7.427l3.396 3.396a.25.25 0 0 0 .354 0l3.396-3.396A.25.25 0 0 0 11.396 7H4.604a.25.25 0 0 0-.177.427z"/>
      </svg>
    </div>
  </button>
</template>

<style scoped>
.era-card {
  width: 100%;
  position: relative;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 0;
  text-align: left;
  transition: all 0.2s ease;
  overflow: hidden;
  cursor: pointer;
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
  width: 56px;
  height: 56px;
  border-radius: 6px;
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
  transition: color 0.3s;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.era-alt-names {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.65);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Desktop-only content: hidden on mobile */
.era-desc,
.era-timeline {
  display: none;
}

/* Expand indicator */
.era-expand-indicator {
  position: absolute;
  bottom: 8px;
  right: 12px;
  color: rgba(255, 255, 255, 0.3);
  transition: color 0.15s;
}

.era-card:hover .era-expand-indicator {
  color: rgba(255, 255, 255, 0.6);
}

.era-expand-indicator svg {
  transition: transform 0.2s ease;
}

.era-expand-indicator .rotated {
  transform: rotate(180deg);
}

/* ── Desktop (768px+) ── */
@media (min-width: 768px) {
  .era-layout {
    align-items: flex-start;
    gap: 20px;
    padding: 16px 20px;
  }

  .era-art {
    width: 80px;
    height: 80px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
  }

  .era-title {
    font-size: 20px;
    margin-bottom: 2px;
  }

  .era-alt-names {
    font-size: 12px;
    margin-bottom: 6px;
  }

  .era-desc {
    display: -webkit-box;
    color: rgba(255, 255, 255, 0.65);
    font-size: 12px;
    line-height: 1.5;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    margin-bottom: 8px;
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
    color: rgba(255, 255, 255, 0.5);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

/* ── Sticky state (all sizes) ── */
.era-card.era-sticky {
  position: sticky;
  top: var(--header-height);
  z-index: 10;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  animation: none;
}

.era-card.era-sticky .era-layout {
  padding: 8px 16px;
  gap: 10px;
  align-items: center;
}

.era-card.era-sticky .era-art {
  width: 32px;
  height: 32px;
  border-radius: 4px;
}

.era-card.era-sticky .era-art svg {
  width: 16px;
  height: 16px;
}

.era-card.era-sticky .era-title {
  font-size: 14px;
  -webkit-line-clamp: 1;
  margin-bottom: 0;
}

.era-card.era-sticky .era-alt-names,
.era-card.era-sticky .era-desc,
.era-card.era-sticky .era-timeline {
  display: none;
}

.era-card.era-sticky .era-expand-indicator {
  bottom: 50%;
  transform: translateY(50%);
}

/* Mobile sticky: remove horizontal borders */
@media (max-width: 767px) {
  .era-card.era-sticky {
    border-radius: 0;
    border-left: none;
    border-right: none;
  }

  .era-expand-indicator {
    bottom: 6px;
    right: 10px;
  }
}

/* Desktop sticky: rounded top corners */
@media (min-width: 768px) {
  .era-card.era-sticky {
    border-radius: 6px 6px 0 0;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
  }

  .era-card.era-sticky .era-layout {
    padding: 10px 16px;
    gap: 12px;
  }

  .era-card.era-sticky .era-art {
    width: 40px;
    height: 40px;
  }

  .era-card.era-sticky .era-title {
    font-size: 15px;
  }

  .era-card.era-sticky .era-expand-indicator {
    right: 16px;
  }
}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  .era-card {
    animation: none;
  }
}
</style>
