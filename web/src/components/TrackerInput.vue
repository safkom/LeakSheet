<script setup>
import { ref } from 'vue'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

const props = defineProps({
  loading: Boolean,
})

const emit = defineEmits(['parse'])

const url = ref('')

function handleSubmit() {
  const trimmed = url.value.trim()
  if (!trimmed) return
  emit('parse', trimmed)
}
</script>

<template>
  <form class="tracker-input" @submit.prevent="handleSubmit">
    <div class="input-wrapper">
      <svg class="input-icon" viewBox="0 0 16 16" width="16" height="16">
        <path fill="currentColor" d="M7.775 3.275a.75.75 0 0 0 1.06 1.06l1.25-1.25a2 2 0 1 1 2.83 2.83l-2.5 2.5a2 2 0 0 1-2.83 0 .75.75 0 0 0-1.06 1.06 3.5 3.5 0 0 0 4.95 0l2.5-2.5a3.5 3.5 0 0 0-4.95-4.95l-1.25 1.25zm-4.69 9.64a2 2 0 0 1 0-2.83l2.5-2.5a2 2 0 0 1 2.83 0 .75.75 0 0 0 1.06-1.06 3.5 3.5 0 0 0-4.95 0l-2.5 2.5a3.5 3.5 0 0 0 4.95 4.95l1.25-1.25a.75.75 0 0 0-1.06-1.06l-1.25 1.25a2 2 0 0 1-2.83 0z"></path>
      </svg>
      <Input
        v-model="url"
        type="text"
        variant="ghost"
        class="flex-1 px-3 py-2.5 text-sm"
        placeholder="Paste a tracker URL (Google Sheets or yetracker.net)..."
        :disabled="loading"
      />
      <Button
        type="submit"
        size="sm"
        :disabled="loading || !url.trim()"
        class="flex-shrink-0 rounded-md"
      >
        <span v-if="loading" class="spinner"></span>
        <span v-else>Parse</span>
      </Button>
    </div>
  </form>
</template>

<style scoped>
.tracker-input {
  width: 100%;
}

.input-wrapper {
  display: flex;
  align-items: center;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 4px 4px 4px 14px;
  transition: all 0.2s ease;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.input-wrapper:focus-within {
  border-color: var(--accent-color);
  box-shadow: 0 0 0 3px var(--accent-dim), 0 4px 12px rgba(0, 0, 0, 0.3);
  transform: translateY(-1px);
}

.input-icon {
  color: var(--text-dim);
  flex-shrink: 0;
}

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid transparent;
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
