<script setup lang="ts">
import { computed } from 'vue'
import { getEraColors } from '../composables/useEraColors'
import type { Era } from '../composables/useEraFiltering'

const props = defineProps<{
  eras: Era[]
  activeEra: string | null
  visible: boolean
}>()

const emit = defineEmits<{
  jump: [eraName: string]
}>()

/** Generate 1-3 letter abbreviation from era name */
function abbrev(name: string): string {
  // Special handling for common patterns
  const clean = name
    .replace(/\[.*?\]/g, '')  // remove [V1], [Demo] etc
    .replace(/\(.*?\)/g, '')  // remove parentheses
    .trim()

  const words = clean.split(/[\s&,_-]+/).filter(Boolean)
  if (words.length === 1) {
    // Single word — take first 2-3 chars
    return words[0].slice(0, 3).toUpperCase()
  }
  // Multi-word — initials, max 3
  return words.slice(0, 3).map(w => w[0]?.toUpperCase() ?? '').join('')
}

function eraAccent(eraName: string): string | null {
  return getEraColors(eraName)?.accent ?? null
}
</script>

<template>
  <Transition name="era-nav">
    <nav v-if="visible && eras.length > 1" class="era-nav" aria-label="Era navigation">
      <div class="era-nav-inner">
        <button
          v-for="era in eras"
          :key="era.name"
          class="era-nav-node"
          :class="{ active: activeEra === era.name }"
          :style="activeEra === era.name && eraAccent(era.name)
            ? { background: eraAccent(era.name)!, color: '#000', boxShadow: `0 0 0 2px ${eraAccent(era.name)}40` }
            : {}"
          :title="era.name"
          :aria-label="`Jump to ${era.name}`"
          :aria-current="activeEra === era.name ? 'true' : undefined"
          @click="emit('jump', era.name)"
        >
          {{ abbrev(era.name) }}
        </button>
      </div>
    </nav>
  </Transition>
</template>

<style scoped>
.era-nav {
  position: fixed;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  z-index: var(--z-sticky);
  /* Hidden on mobile */
  display: none;
}

/* Desktop only */
@media (min-width: 1024px) {
  .era-nav {
    display: block;
  }
}

.era-nav-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 6px 4px;
  background: rgba(10, 10, 10, 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 12px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  scrollbar-width: none;
}

.era-nav-inner::-webkit-scrollbar {
  display: none;
}

.era-nav-node {
  width: 28px;
  height: 22px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 7.5px;
  font-weight: 700;
  letter-spacing: 0.2px;
  color: rgba(255, 255, 255, 0.3);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: color 0.15s, background 0.15s, box-shadow 0.15s, transform 0.1s;
  -webkit-tap-highlight-color: transparent;
  line-height: 1;
  white-space: nowrap;
  overflow: hidden;
  padding: 0 3px;
}

.era-nav-node:hover {
  color: rgba(255, 255, 255, 0.8);
  background: rgba(255, 255, 255, 0.08);
  transform: scale(1.1);
}

.era-nav-node.active {
  color: #000;
  font-weight: 800;
}

/* Appear animation */
.era-nav-enter-active {
  transition: opacity 0.3s ease 0.4s, transform 0.3s ease 0.4s;
}
.era-nav-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.era-nav-enter-from {
  opacity: 0;
  transform: translateY(-50%) translateX(8px);
}
.era-nav-leave-to {
  opacity: 0;
  transform: translateY(-50%) translateX(8px);
}

@media (prefers-reduced-motion: reduce) {
  .era-nav-enter-active,
  .era-nav-leave-active {
    transition: opacity 0.2s ease;
  }
  .era-nav-enter-from,
  .era-nav-leave-to {
    transform: translateY(-50%);
  }
}
</style>
