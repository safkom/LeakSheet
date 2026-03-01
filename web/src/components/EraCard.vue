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
const colorThief = new ColorThief()
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
    const dom = colorThief.getColor(imgElement)
    const pal = colorThief.getPalette(imgElement, 5)

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
  // Defer color extraction to avoid blocking the main thread during initial load
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(() => extractColors(img), { timeout: 2000 })
  } else {
    setTimeout(() => extractColors(img), 100)
  }
}

function onImgError(e) {
  // Retry failed images up to MAX_RETRIES times
  if (e.target && imgRetries.value < MAX_RETRIES) {
    imgRetries.value++
    // Retry after a small delay with cache-busting
    setTimeout(() => {
      if (e.target && artSrc.value) {
        const sep = artSrc.value.includes('?') ? '&' : '?'
        e.target.src = `${artSrc.value}${sep}_r=${imgRetries.value}`
      }
    }, 500 * imgRetries.value)
    return
  }
  // Give up — show placeholder
  if (e.target) {
    e.target.style.display = 'none'
    const wrapper = e.target.parentElement
    if (wrapper) {
      wrapper.classList.add('img-error')
    }
  }
}
</script>

<template>
  <button
    class="era-card"
    :class="{ expanded, 'has-colors': colorsReady, 'era-sticky': sticky }"
    :style="gradientStyle"
    @click="emit('click')"
  >
    <!-- Mobile layout: centered art + title below -->
    <div class="era-card-mobile">
      <div class="era-art-wrapper" v-if="artSrc">
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
          <svg viewBox="0 0 24 24" width="32" height="32">
            <path fill="currentColor" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55C7.79 13 6 14.79 6 17s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
          </svg>
        </div>
      </div>
      <div class="era-art-placeholder" v-else>
        <svg viewBox="0 0 24 24" width="32" height="32">
          <path fill="currentColor" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55C7.79 13 6 14.79 6 17s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
        </svg>
      </div>
      <div class="era-title-group">
        <h3 class="era-title-mobile" :style="{ color: titleColor }">{{ era.name }}</h3>
        <div v-if="era.alt_names?.length" class="era-alt-names">{{ era.alt_names.join(', ') }}</div>
      </div>
    </div>

    <!-- Desktop layout: art left, info right -->
    <div class="era-card-desktop">
      <div class="era-art-desktop" v-if="artSrc">
        <img
          :src="artSrc"
          alt=""
          :loading="index < 6 ? 'eager' : 'lazy'"
          crossorigin="anonymous"
          @load="onImgLoad"
          @error="onImgError"
          class="era-art-img-desktop"
        />
        <div class="era-art-fallback era-art-fallback-desktop">
          <svg viewBox="0 0 24 24" width="28" height="28">
            <path fill="currentColor" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55C7.79 13 6 14.79 6 17s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
          </svg>
        </div>
      </div>
      <div class="era-art-desktop era-art-placeholder-desktop" v-else>
        <svg viewBox="0 0 24 24" width="28" height="28">
          <path fill="currentColor" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55C7.79 13 6 14.79 6 17s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
        </svg>
      </div>

      <div class="era-info-desktop">
        <h3 class="era-title-desktop" :style="{ color: titleColor }">{{ era.name }}</h3>
        <div v-if="era.alt_names?.length" class="era-alt-names era-alt-names-desktop">{{ era.alt_names.join(', ') }}</div>

        <p v-if="era.description" class="era-desc-desktop">{{ era.description }}</p>

        <div v-if="era.timeline?.length" class="era-timeline-desktop">
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
      <svg
        viewBox="0 0 16 16"
        width="14"
        height="14"
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
  position: relative;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 0;
  text-align: left;
  transition: all 0.2s ease;
  overflow: hidden;
  cursor: pointer;
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

/* ── Mobile layout ── */
.era-card-mobile {
  display: flex;
  flex-direction: row;
  align-items: center;
  padding: 14px 16px;
  gap: 14px;
}

.era-card-desktop {
  display: none;
}

.era-art-wrapper {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  flex-shrink: 0;
  position: relative;
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

.img-error .era-art-img,
.img-error .era-art-img-desktop {
  display: none !important;
}

.img-error .era-art-fallback {
  display: flex;
}

.era-art-placeholder {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  flex-shrink: 0;
}

.era-title-group {
  flex: 1;
  min-width: 0;
  text-align: left;
}

.era-title-mobile {
  font-size: 16px;
  font-weight: 700;
  text-align: left;
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

/* ── Desktop layout ── */
@media (min-width: 768px) {
  .era-card-mobile {
    display: none;
  }

  .era-card-desktop {
    display: flex;
    align-items: flex-start;
    gap: 20px;
    padding: 16px 20px;
  }

  .era-art-desktop {
    width: 80px;
    height: 80px;
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
    flex-shrink: 0;
  }

  .era-art-img-desktop {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .era-art-placeholder-desktop {
    background: rgba(255, 255, 255, 0.05);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-dim);
  }

  .era-info-desktop {
    flex: 1;
    min-width: 0;
  }

  .era-title-desktop {
    font-size: 20px;
    font-weight: 700;
    line-height: 1.2;
    margin-bottom: 2px;
    transition: color 0.3s;
  }

  .era-alt-names-desktop {
    font-size: 12px;
    margin-bottom: 6px;
  }

  .era-desc-desktop {
    color: rgba(255, 255, 255, 0.65);
    font-size: 12px;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    margin-bottom: 8px;
  }

  .era-timeline-desktop {
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


/* ── Expand indicator ── */
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

/* ── Sticky era card (mobile) ── */
@media (max-width: 767px) {
  .era-expand-indicator {
    bottom: 6px;
    right: 10px;
  }

  .era-card.era-sticky {
    position: sticky;
    top: var(--header-height);
    z-index: 10;
    border-radius: 0;
    border-left: none;
    border-right: none;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  }

  .era-card.era-sticky .era-card-mobile {
    padding: 8px 16px;
    gap: 10px;
  }

  .era-card.era-sticky .era-art-wrapper {
    width: 32px;
    height: 32px;
    border-radius: 4px;
  }

  .era-card.era-sticky .era-art-placeholder {
    width: 32px;
    height: 32px;
    border-radius: 4px;
  }

  .era-card.era-sticky .era-art-placeholder svg,
  .era-card.era-sticky .era-art-wrapper svg {
    width: 16px;
    height: 16px;
  }

  .era-card.era-sticky .era-title-mobile {
    font-size: 14px;
    -webkit-line-clamp: 1;
  }

  .era-card.era-sticky .era-alt-names {
    display: none;
  }

  .era-card.era-sticky .era-expand-indicator {
    bottom: 50%;
    transform: translateY(50%);
    right: 10px;
  }
}

/* ── Sticky era card (desktop) ── */
@media (min-width: 768px) {
  .era-card.era-sticky {
    position: sticky;
    top: var(--header-height);
    z-index: 10;
    border-radius: 6px 6px 0 0;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
  }

  .era-card.era-sticky .era-card-desktop {
    padding: 10px 16px;
    gap: 12px;
    align-items: center;
  }

  .era-card.era-sticky .era-art-desktop {
    width: 40px;
    height: 40px;
    border-radius: 4px;
  }

  .era-card.era-sticky .era-desc-desktop,
  .era-card.era-sticky .era-timeline-desktop,
  .era-card.era-sticky .era-alt-names-desktop {
    display: none;
  }

  .era-card.era-sticky .era-title-desktop {
    font-size: 15px;
    margin-bottom: 0;
  }

  .era-card.era-sticky .era-expand-indicator {
    bottom: 50%;
    transform: translateY(50%);
    right: 16px;
  }
}
</style>
