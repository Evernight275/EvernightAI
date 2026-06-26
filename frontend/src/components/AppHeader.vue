<script setup lang="ts">
import Icon from './Icon.vue'

const emit = defineEmits<{
  configureApiKey: []
}>()
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <Icon name="bot" />
      <span>Agent Console</span>
    </div>
    <div class="user-area">
      <button
        class="button icon-button"
        type="button"
        title="设置 API Key"
        aria-label="设置 API Key"
        @click="emit('configureApiKey')"
      >
        <Icon name="user-round" />
      </button>
    </div>
  </header>
</template>
