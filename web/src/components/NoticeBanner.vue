<script setup lang="ts">
import { computed } from 'vue'
import type { Notice } from '../composables/useEraFiltering'

const props = defineProps<{
  notices: Notice[]
}>()

const emit = defineEmits<{
  dismiss: []
}>()

const alerts = computed(() => props.notices.filter(n => n.kind === 'alert'))
const links = computed(() => props.notices.filter(n => n.kind !== 'alert'))
</script>

<template>
  <div class="notice-wrapper">
    <!-- Alert notices (urgent warnings) -->
    <div v-if="alerts.length" class="notice-banner notice-alert" role="alert">
      <svg class="notice-icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <path fill="currentColor" d="M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0 1 14.082 15H1.918a1.75 1.75 0 0 1-1.543-2.575ZM8 5a.75.75 0 0 0-.75.75v2.5a.75.75 0 0 0 1.5 0v-2.5A.75.75 0 0 0 8 5Zm0 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"/>
      </svg>
      <div class="notice-text">
        <p v-for="(notice, i) in alerts" :key="'a'+i">
          <a v-if="notice.link" :href="notice.link" target="_blank" rel="noopener noreferrer" class="notice-link alert-link">{{ notice.text }}</a>
          <template v-else>{{ notice.text }}</template>
        </p>
      </div>
      <button v-if="!links.length" class="notice-dismiss" @click="emit('dismiss')" aria-label="Dismiss notice">
        <svg viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
        </svg>
      </button>
    </div>

    <!-- Info notices (links, general info) -->
    <div v-if="links.length" class="notice-banner notice-info">
      <svg class="notice-icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <path fill="currentColor" d="M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm8-6.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM6.5 7.75A.75.75 0 0 1 7.25 7h1a.75.75 0 0 1 .75.75v2.75h.25a.75.75 0 0 1 0 1.5h-2a.75.75 0 0 1 0-1.5h.25v-2h-.25a.75.75 0 0 1-.75-.75ZM8 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z"/>
      </svg>
      <div class="notice-text">
        <p v-for="(notice, i) in links" :key="'l'+i">
          <a v-if="notice.link" :href="notice.link" target="_blank" rel="noopener noreferrer" class="notice-link info-link">{{ notice.text }}</a>
          <template v-else>{{ notice.text }}</template>
        </p>
      </div>
      <button class="notice-dismiss" @click="emit('dismiss')" aria-label="Dismiss notice">
        <svg viewBox="0 0 16 16" width="14" height="14">
          <path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06z"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.notice-wrapper {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.notice-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.5;
}

/* Alert: amber/warning */
.notice-alert {
  background: rgba(234, 179, 8, 0.10);
  border: 1px solid rgba(234, 179, 8, 0.25);
  color: #fbbf24;
}

/* Info: neutral/blue-gray */
.notice-info {
  background: rgba(148, 163, 184, 0.08);
  border: 1px solid rgba(148, 163, 184, 0.18);
  color: #94a3b8;
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

.notice-link {
  text-decoration: underline;
  text-underline-offset: 2px;
  transition: color 0.15s;
}

.alert-link {
  color: #fbbf24;
}
.alert-link:hover {
  color: #fde68a;
}

.info-link {
  color: #94a3b8;
}
.info-link:hover {
  color: #cbd5e1;
}

.notice-dismiss {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, background 0.15s;
  margin: -4px -4px -4px 0;
}

.notice-alert .notice-dismiss {
  color: rgba(251, 191, 36, 0.6);
}
.notice-alert .notice-dismiss:hover {
  color: #fbbf24;
  background: rgba(234, 179, 8, 0.12);
}

.notice-info .notice-dismiss {
  color: rgba(148, 163, 184, 0.5);
}
.notice-info .notice-dismiss:hover {
  color: #94a3b8;
  background: rgba(148, 163, 184, 0.10);
}
</style>
