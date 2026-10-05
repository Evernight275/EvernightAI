<script setup lang="ts">
import { Wrench, Check, Clock, CircleAlert } from '@lucide/vue';
import { useChatToolActivity, type ChatToolActivityProps } from './chatToolActivity';
import JsonCode from '../common/JsonCode.vue';
import ToolOutput from '../common/ToolOutput.vue';
import ToolDuration from './ToolDuration.vue';
import ChatToolDisplay from './ChatToolDisplay.vue';

const props = defineProps<ChatToolActivityProps>();
const { activities } = useChatToolActivity(props);
</script>

<template>
  <section class="chat-tool-activity">
    <h2>工具调用（{{ activities.length }}）</h2>
    <div v-if="!activities.length" class="chat-tool-empty">
      <span><Wrench :size="20" aria-hidden="true" /></span>
      <p>还没有工具调用<small>需要使用工具时，执行记录会显示在这里。</small></p>
    </div>
    <ol v-else>
      <li v-for="activity in activities" :key="activity.key">
        <div class="chat-tool-entry-heading">
          <span class="chat-tool-entry-icon"
            ><Check
              v-if="activity.status === 'completed'"
              :size="15"
              aria-hidden="true" /><CircleAlert
              v-else-if="activity.status === 'failed'"
              :size="15"
              aria-hidden="true" /><Clock v-else :size="15" aria-hidden="true" /></span
          ><strong>{{ activity.name }}</strong
          ><ToolDuration
            :started-at="activity.startedAt"
            :finished-at="activity.finishedAt"
            :duration-ms="activity.durationMs"
            :running="activity.status === 'running'"
          /><span
            class="chat-tool-entry-status"
            :class="{ 'is-error': activity.status === 'failed' }"
            >{{ activity.statusLabel }}</span
          >
        </div>
        <ChatToolDisplay
          v-if="activity.status === 'completed'"
          :name="activity.name"
          :result-text="activity.resultText ?? undefined"
        />
        <details class="chat-raw-details">
          <summary>调用参数</summary>
          <ToolOutput :source="activity.callText" :label="activity.name + ' 调用参数'">
            <pre
              tabindex="0"
              :aria-label="activity.name + ' 调用参数'"
            ><JsonCode :source="activity.callText" /></pre>
          </ToolOutput>
        </details>
        <details v-if="activity.resultText" class="chat-raw-details">
          <summary>调用结果</summary>
          <ToolOutput :source="activity.resultText" :label="activity.name + ' 调用结果'">
            <pre
              tabindex="0"
              :aria-label="activity.name + ' 调用结果'"
            ><JsonCode :source="activity.resultText" /></pre>
          </ToolOutput>
        </details>
      </li>
    </ol>
  </section>
</template>
