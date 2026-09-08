<script setup lang="ts">
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
    <p v-if="!activities.length">还没有工具调用</p>
    <ol v-else>
      <li v-for="activity in activities" :key="activity.key">
        {{ activity.name }} / {{ activity.statusLabel }}
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
