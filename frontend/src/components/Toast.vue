<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Icon from './Icon.vue'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface ToastMessage {
  id: string
  type: ToastType
  message: string
  duration?: number
}

const props = defineProps<{
  toast: ToastMessage
}>()

const emit = defineEmits<{
  remove: [id: string]
}>()

const visible = ref(false)
const progress = ref(100)
const timerId = ref<number | null>(null)
const progressTimerId = ref<number | null>(null)

const iconName = computed(() => {
  switch (props.toast.type) {
    case 'success':
      return 'check-circle'
    case 'error':
      return 'x-circle'
    case 'warning':
      return 'alert-triangle'
    case 'info':
      return 'info'
    default:
      return 'info'
  }
})

const duration = computed(() => props.toast.duration || 3000)

function close() {
  visible.value = false
  setTimeout(() => {
    emit('remove', props.toast.id)
  }, 300)
}

function startTimer() {
  const startTime = Date.now()
  const updateInterval = 50

  progressTimerId.value = window.setInterval(() => {
    const elapsed = Date.now() - startTime
    progress.value = Math.max(0, 100 - (elapsed / duration.value) * 100)
  }, updateInterval)

  timerId.value = window.setTimeout(() => {
    close()
  }, duration.value)
}

function pauseTimer() {
  if (timerId.value) {
    clearTimeout(timerId.value)
    timerId.value = null
  }
  if (progressTimerId.value) {
    clearInterval(progressTimerId.value)
    progressTimerId.value = null
  }
}

function resumeTimer() {
  if (timerId.value === null) {
    const remainingTime = (progress.value / 100) * duration.value

    const startTime = Date.now()
    progressTimerId.value = window.setInterval(() => {
      const elapsed = Date.now() - startTime
      progress.value = Math.max(0, (remainingTime - elapsed) / duration.value * 100)
    }, 50)

    timerId.value = window.setTimeout(() => {
      close()
    }, remainingTime)
  }
}

onMounted(() => {
  visible.value = true
  startTimer()
})
</script>

<template>
  <div
    class="toast-item"
    :class="[`toast-${toast.type}`, { 'toast-visible': visible }]"
    :role="toast.type === 'error' ? 'alert' : 'status'"
    :aria-live="toast.type === 'error' ? 'assertive' : 'polite'"
    @mouseenter="pauseTimer"
    @mouseleave="resumeTimer"
  >
    <div class="toast-content">
      <Icon :name="iconName" class="toast-icon" />
      <span class="toast-message">{{ toast.message }}</span>
      <button
        class="toast-close"
        type="button"
        title="关闭"
        aria-label="关闭通知"
        @click="close"
      >
        <Icon name="x" />
      </button>
    </div>
    <div class="toast-progress">
      <div class="toast-progress-bar" :style="{ width: `${progress}%` }"></div>
    </div>
  </div>
</template>

<style scoped>
.toast-item {
  width: 100%;
  max-width: 420px;
  display: grid;
  gap: 0;
  border-radius: 8px;
  background: var(--paper);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  overflow: hidden;
  transform: translateY(20px);
  opacity: 0;
  transition: transform 300ms cubic-bezier(0.2, 0.8, 0.2, 1), opacity 300ms ease;
}

.toast-item.toast-visible {
  transform: translateY(0);
  opacity: 1;
}

.toast-content {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 14px 16px;
}

.toast-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

.toast-message {
  color: var(--ink);
  font-size: 14px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.toast-close {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 4px;
  color: var(--muted);
  background: transparent;
  cursor: pointer;
  transition: color 140ms ease, background-color 140ms ease;
}

.toast-close:hover {
  color: var(--ink);
  background: var(--soft);
}

.toast-close .icon {
  width: 16px;
  height: 16px;
}

.toast-progress {
  height: 3px;
  background: var(--soft);
  overflow: hidden;
}

.toast-progress-bar {
  height: 100%;
  transition: width 50ms linear;
}

/* Success */
.toast-success .toast-icon {
  color: var(--success);
}

.toast-success .toast-progress-bar {
  background: var(--success);
}

/* Error */
.toast-error .toast-icon {
  color: var(--danger);
}

.toast-error .toast-progress-bar {
  background: var(--danger);
}

/* Warning */
.toast-warning .toast-icon {
  color: var(--warning);
}

.toast-warning .toast-progress-bar {
  background: var(--warning);
}

/* Info */
.toast-info .toast-icon {
  color: var(--info);
}

.toast-info .toast-progress-bar {
  background: var(--info);
}
</style>
