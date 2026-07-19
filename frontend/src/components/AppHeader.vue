<script setup lang="ts">
import Icon from './Icon.vue'

defineProps<{
  healthOk: boolean
}>()

const emit = defineEmits<{
  configureApiKey: []
}>()
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <span class="brand-mark"><Icon name="bot" /></span>
      <span class="brand-copy">
        <strong>EvernightAI</strong>
        <small>Agent Platform</small>
      </span>
    </div>
    <div class="user-area">
      <span class="global-health" :class="{ 'is-online': healthOk }">
        <span class="health-dot"></span>
        <span>{{ healthOk ? 'Runtime 正常' : 'Runtime 未连接' }}</span>
      </span>
      <button
        class="button api-key-button"
        type="button"
        title="设置 API Key"
        aria-label="设置 API Key"
        @click="emit('configureApiKey')"
      >
        <Icon name="key-round" />
        <span>API Key</span>
      </button>
    </div>
  </header>
</template>
