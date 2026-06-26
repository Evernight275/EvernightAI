<script setup lang="ts">
defineProps<{
  activeAgents: number
  activeSessions: number
  toolCount: number
  successRate: number
}>()
</script>

<template>
  <section class="metrics" aria-label="核心指标">
    <article class="metric">
      <p class="metric-label">活跃 Agent</p>
      <p class="metric-value">{{ activeAgents }}</p>
    </article>
    <article class="metric">
      <p class="metric-label">运行中会话</p>
      <p class="metric-value">{{ activeSessions }}</p>
    </article>
    <article class="metric">
      <p class="metric-label">工具调用</p>
      <p class="metric-value">{{ toolCount }}</p>
    </article>
    <article class="metric">
      <p class="metric-label">任务成功率</p>
      <p class="metric-value">{{ successRate }}%</p>
    </article>
  </section>
</template>
