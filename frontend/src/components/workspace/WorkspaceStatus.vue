<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  state: string
  loadedAt: string | null
  connectionError: unknown
}>()

defineEmits<{
  refresh: []
}>()

const stateLabel = computed(() => ({
  idle: '未启动',
  loading: '加载中',
  ready: '就绪',
  degraded: '部分可用',
  unauthorized: '需要认证',
  offline: '后端不可用',
}[props.state] || props.state))

const errorMessage = computed(() => {
  if (!props.connectionError) {
    return null
  }
  return props.connectionError instanceof Error
    ? props.connectionError.message
    : String(props.connectionError)
})
</script>

<template>
  <section>
    <h2>状态</h2>
    <p>{{ stateLabel }}</p>
    <p v-if="loadedAt">最后加载：{{ loadedAt }}</p>
    <p v-if="errorMessage">{{ errorMessage }}</p>
    <button type="button" :disabled="state === 'loading'" @click="$emit('refresh')">
      刷新
    </button>
  </section>
</template>
