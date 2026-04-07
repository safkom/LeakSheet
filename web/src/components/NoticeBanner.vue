<script setup lang="ts">
defineProps<{
  notices: string[]
}>()

const emit = defineEmits<{
  dismiss: []
}>()
</script>

<template>
  <div class="notice-banner" role="alert">
    <svg class="notice-icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path fill="currentColor" d="M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0 1 14.082 15H1.918a1.75 1.75 0 0 1-1.543-2.575ZM8 5a.75.75 0 0 0-.75.75v2.5a.75.75 0 0 0 1.5 0v-2.5A.75.75 0 0 0 8 5Zm0 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"/>
    </svg>
    <div class="notice-text">
      <p v-for="(notice, i) in notices" :key="i">{{ notice }}</p>
    </div>
    <button class="notice-dismiss" @click="emit('dismiss')" aria-label="Dismiss notice">
      <svg viewBox="0 0 16 16" width="14" height="14">
        <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
      </svg>
    </button>
  </div>
</template>

<style scoped>
.notice-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 16px;
  border-radius: 10px;
  background: rgba(234, 179, 8, 0.10);
  border: 1px solid rgba(234, 179, 8, 0.25);
  color: #fbbf24;
  font-size: 13px;
  line-height: 1.5;
}

.notice-icon {
  flex-shrink: 0;
  margin-top: 2px;
  opacity: 0.85;
}

.notice-text {
  flex: 1;
  min-width: 0;
}

.notice-text p {
  margin: 0;
}

.notice-text p + p {
  margin-top: 4px;
}

.notice-dismiss {
  flex-shrink: 0;
  color: rgba(251, 191, 36, 0.6);
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, background 0.15s;
  margin: -4px -4px -4px 0;
}

.notice-dismiss:hover {
  color: #fbbf24;
  background: rgba(234, 179, 8, 0.12);
}
</style>
