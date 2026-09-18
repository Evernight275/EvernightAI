<script setup lang="ts">
import { computed } from 'vue'
import { Check, ChevronRight, CircleAlert, Clock, Wrench } from '@lucide/vue'
import type { ChatTranscriptEntry } from '../../domain/chat'

const props = defineProps<{ activity: NonNullable<ChatTranscriptEntry['toolActivity']> }>()
const labels = {
  pending: '准备调用',
  approval: '等待审批',
  completed: '已完成',
  failed: '失败',
  denied: '已拒绝',
  unknown: '调用记录',
}
const status = computed(() => labels[props.activity.status])
const target = computed(() => {
  try {
    const args = JSON.parse(props.activity.argumentsText)
    return (
      [args.path, args.file_path, args.command, args.query, args.url].find(
        (value) => typeof value === 'string',
      ) || ''
    )
  } catch {
    return ''
  }
})
</script>
<template>
  <details
    class="chat-inline-tool"
    :class="{ 'is-error': activity.status === 'failed' || activity.status === 'denied' }"
  >
    <summary>
      <Check v-if="activity.status === 'completed'" :size="15" aria-hidden="true" />
      <CircleAlert
        v-else-if="activity.status === 'failed' || activity.status === 'denied'"
        :size="15"
        aria-hidden="true"
      />
      <Clock v-else-if="activity.status === 'approval'" :size="15" aria-hidden="true" />
      <Wrench v-else :size="15" aria-hidden="true" />
      <span class="chat-inline-tool-name">{{ activity.name }}</span>
      <span v-if="target" class="chat-inline-tool-target" :title="target">{{ target }}</span>
      <span class="chat-inline-tool-status">{{ status }}</span
      ><ChevronRight class="chat-inline-tool-chevron" :size="14" aria-hidden="true" />
    </summary>
    <div class="chat-inline-tool-details">
      <p v-if="activity.status === 'approval'">请在输入框上方批准或拒绝此调用。</p>
      <h4>调用参数</h4>
      <pre tabindex="0" :aria-label="activity.name + ' 调用参数'">{{ activity.argumentsText }}</pre>
      <template v-if="activity.resultText"
        ><h4>调用结果</h4>
        <pre tabindex="0" :aria-label="activity.name + ' 调用结果'">{{ activity.resultText }}</pre>
      </template>
    </div>
  </details>
</template>
