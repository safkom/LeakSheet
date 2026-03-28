<script setup lang="ts">
defineProps<{
  visible: boolean
}>()

defineEmits<{
  click: []
}>()
</script>

<template>
  <Transition name="scroll-top">
    <button
      v-if="visible"
      class="scroll-top-btn"
      aria-label="Scroll to top"
      @click="$emit('click')"
    >
      <svg viewBox="0 0 16 16" width="16" height="16">
        <path fill="currentColor" d="M3.47 7.78a.75.75 0 0 1 0-1.06l4.25-4.25a.75.75 0 0 1 1.06 0l4.25 4.25a.751.751 0 0 1-1.042 1.042L9 4.81v7.44a.75.75 0 0 1-1.5 0V4.81L4.53 7.78a.75.75 0 0 1-1.06 0z"/>
      </svg>
    </button>
  </Transition>
</template>

<style scoped>
.scroll-top-btn {
  position: fixed;
  bottom: calc(var(--player-height, 72px) + 20px);
  right: 16px;
  z-index: var(--z-sticky);
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: rgba(15, 15, 15, 0.85);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: color 0.15s, background 0.15s, border-color 0.15s, transform 0.1s;
  -webkit-tap-highlight-color: transparent;
  /* Only visible on mobile */
  display: none;
}

@media (max-width: 1023px) {
  .scroll-top-btn {
    display: flex;
  }
}

.scroll-top-btn:hover {
  color: var(--text-primary);
  background: rgba(25, 25, 25, 0.95);
  border-color: rgba(255, 255, 255, 0.2);
}

.scroll-top-btn:active {
  transform: scale(0.92);
}

.scroll-top-enter-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.scroll-top-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.scroll-top-enter-from,
.scroll-top-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (prefers-reduced-motion: reduce) {
  .scroll-top-enter-from,
  .scroll-top-leave-to {
    transform: none;
  }
}
</style>
