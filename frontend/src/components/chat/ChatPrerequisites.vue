<script setup lang="ts">
import WorkspaceIssues from '../workspace/WorkspaceIssues.vue'
import {
  useChatPrerequisites,
  type ChatPrerequisitesProps,
} from './chatPrerequisites'

const props = defineProps<ChatPrerequisitesProps>()
const { notice } = useChatPrerequisites(props)
</script>

<template>
  <section class="chat-prerequisites">
    <dl class="chat-environment-grid">
      <div><dt>工作区</dt><dd>{{ ({ ready: '已连接', loading: '连接中', offline: '离线', unauthorized: '需要认证', degraded: '部分可用', idle: '未连接' } as Record<string, string>)[state] || state }}</dd></div>
      <div><dt>模型服务</dt><dd>{{ providerCount }}<small> 个</small></dd></div>
      <div><dt>可用工具</dt><dd>{{ toolCount }}<small> 个</small></dd></div>
    </dl>
    <p v-if="notice">{{ notice }}</p>
    <WorkspaceIssues :issues="issues" />
  </section>
</template>
