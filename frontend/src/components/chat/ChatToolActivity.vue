<script setup lang="ts">
import { Wrench, Check, Clock, CircleAlert } from '@lucide/vue'
import {
  useChatToolActivity,
  type ChatToolActivityProps,
} from './chatToolActivity'

const props = defineProps<ChatToolActivityProps>()
const { activities } = useChatToolActivity(props)
</script>

<template>
  <section class="chat-tool-activity">
    <h2>工具调用（{{ activities.length }}）</h2>
    <div v-if="!activities.length" class="chat-tool-empty"><span><Wrench :size="20" aria-hidden="true" /></span><p>还没有工具调用<small>需要使用工具时，执行记录会显示在这里。</small></p></div>
    <ol v-else>
      <li v-for="activity in activities" :key="activity.key">
        <div class="chat-tool-entry-heading"><span class="chat-tool-entry-icon"><Check v-if="activity.status === 'completed'" :size="15" aria-hidden="true" /><CircleAlert v-else-if="activity.status === 'failed'" :size="15" aria-hidden="true" /><Clock v-else :size="15" aria-hidden="true" /></span><strong>{{ activity.name }}</strong><span class="chat-tool-entry-status" :class="{ 'is-error': activity.status === 'failed' }">{{ activity.statusLabel }}</span></div>
        <details class="chat-raw-details">
          <summary>调用参数</summary>
          <pre tabindex="0" :aria-label="activity.name + ' 调用参数'">{{ activity.callText }}</pre>
        </details>
        <details v-if="activity.resultText" class="chat-raw-details">
          <summary>调用结果</summary>
          <pre tabindex="0" :aria-label="activity.name + ' 调用结果'">{{ activity.resultText }}</pre>
        </details>
      </li>
    </ol>
  </section>
</template>
