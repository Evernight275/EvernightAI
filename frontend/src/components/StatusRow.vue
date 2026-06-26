<script setup lang="ts">
import Icon from './Icon.vue'

defineProps<{
  currentModel: string
  queueStatus: string
  memoryStatus: string
}>()
</script>

<template>
  <footer class="status-row" aria-label="运行状态">
    <div class="status-item">
      <Icon name="bot" />
      <strong>当前模型</strong>
      <span>{{ currentModel }}</span>
    </div>
    <div class="status-item">
      <Icon name="clock" />
      <strong>队列状态</strong>
      <span>{{ queueStatus }}</span>
    </div>
    <div class="status-item">
      <Icon name="database" />
      <strong>记忆库</strong>
      <span>{{ memoryStatus }}</span>
    </div>
  </footer>
</template>
