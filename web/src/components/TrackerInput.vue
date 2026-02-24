<script setup>
import { ref } from 'vue'

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
      <input
        v-model="url"
        type="text"
        class="url-input"
        placeholder="Paste a tracker URL (Google Sheets or yetracker.net)..."
        :disabled="loading"
      />
      <button type="submit" class="parse-btn" :disabled="loading || !url.trim()">
        <span v-if="loading" class="spinner"></span>
        <span v-else>Parse</span>
      </button>
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
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 4px 4px 4px 14px;
  transition: border-color 0.15s;
}

.input-wrapper:focus-within {
  border-color: var(--accent);
}

.input-icon {
  color: var(--text-dim);
  flex-shrink: 0;
}

.url-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  padding: 10px 12px;
  font-size: 14px;
  color: var(--text-primary);
}

.url-input::placeholder {
  color: var(--text-dim);
}

.parse-btn {
  flex-shrink: 0;
  background: var(--accent);
  color: var(--bg-primary);
  font-weight: 600;
  font-size: 13px;
  padding: 8px 20px;
  border-radius: var(--radius-sm);
  transition: background 0.15s;
}

.parse-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.parse-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid transparent;
  border-top-color: var(--bg-primary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 640px) {
  .url-input {
    font-size: 13px;
    padding: 8px 8px;
  }
  .parse-btn {
    padding: 8px 14px;
    font-size: 12px;
  }
}
</style>
