<script setup lang="ts">
import { ref } from 'vue'
import Toast, { type ToastMessage, type ToastType } from './Toast.vue'

const toasts = ref<ToastMessage[]>([])
let toastIdCounter = 0

function generateId(): string {
  return `toast-${Date.now()}-${toastIdCounter++}`
}

function addToast(type: ToastType, message: string, duration?: number) {
  const id = generateId()
  toasts.value.push({
    id,
    type,
    message,
    duration,
  })
}

function removeToast(id: string) {
  const index = toasts.value.findIndex((toast) => toast.id === id)
  if (index !== -1) {
    toasts.value.splice(index, 1)
  }
}

function success(message: string, duration?: number) {
  addToast('success', message, duration)
}

function error(message: string, duration?: number) {
  addToast('error', message, duration)
}

function warning(message: string, duration?: number) {
  addToast('warning', message, duration)
}

function info(message: string, duration?: number) {
  addToast('info', message, duration)
}

defineExpose({
  success,
  error,
  warning,
  info,
})
</script>

<template>
  <div class="toast-container">
    <TransitionGroup name="toast-list">
      <Toast
        v-for="toast in toasts"
        :key="toast.id"
        :toast="toast"
        @remove="removeToast"
      />
    </TransitionGroup>
  </div>
</template>

<style>
.toast-container {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 9999;
  display: grid;
  gap: 12px;
  width: 100%;
  max-width: 420px;
  pointer-events: none;
}

.toast-container > * {
  pointer-events: auto;
}

.toast-list-move,
.toast-list-enter-active,
.toast-list-leave-active {
  transition: all 300ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.toast-list-enter-from {
  transform: translateX(100%);
  opacity: 0;
}

.toast-list-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

.toast-list-leave-active {
  position: absolute;
}

@media (max-width: 560px) {
  .toast-container {
    top: 10px;
    right: 10px;
    left: 10px;
    max-width: none;
  }
}
</style>
