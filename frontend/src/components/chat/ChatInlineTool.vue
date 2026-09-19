<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { Check, ChevronRight, CircleAlert, Clock, LoaderCircle, Wrench } from '@lucide/vue'
import { toolStatusLabels, type ChatTranscriptEntry } from '../../domain/chat'
import type { ChatApprovalItem } from './chatRequestStatus'
import ChatToolApproval from './ChatToolApproval.vue'
import { toolResultSummary } from './toolResult'

const props = defineProps<{
  activity: NonNullable<ChatTranscriptEntry['toolActivity']>
  approval?: ChatApprovalItem
}>()
defineEmits<{ approve: [approvalId: string]; deny: [approvalId: string] }>()
const details = ref<HTMLDetailsElement>()
const result = ref<HTMLPreElement>()
const status = computed(() =>
  props.approval?.decisionText === '已拒绝'
    ? 'failed'
    : props.approval?.decisionText === '已批准'
      ? 'pending'
      : props.activity.status,
)
const summary = computed(() => toolResultSummary(props.activity.resultText))
const target = computed(() => {
  try {
    const args = JSON.parse(props.activity.argumentsText)
    const path =
      [args.path, args.file_path, args.directory, args.command, args.query, args.url].find(
        (value) => typeof value === 'string',
      ) || ''
    const line = args.line ?? args.start_line
    return path && Number.isInteger(line) ? `${path}:${line}` : path
  } catch {
    return ''
  }
})
async function locateError() {
  if (details.value) details.value.open = true
  await nextTick()
  result.value?.focus({ preventScroll: true })
  result.value?.scrollIntoView({ block: 'nearest', behavior: 'auto' })
}
</script>
<template>
  <article class="chat-tool-card" :class="{ 'is-error': status === 'failed' }">
    <details ref="details" class="chat-inline-tool" :class="{ 'is-error': status === 'failed' }">
      <summary>
        <Check v-if="status === 'completed'" :size="15" aria-hidden="true" />
        <CircleAlert v-else-if="status === 'failed'" :size="15" aria-hidden="true" />
        <Clock v-else-if="status === 'approval'" :size="15" aria-hidden="true" />
        <LoaderCircle
          v-else-if="status === 'running'"
          class="chat-tool-spinner"
          :size="15"
          aria-hidden="true"
        />
        <Wrench v-else :size="15" aria-hidden="true" />
        <span class="chat-inline-tool-name">{{ activity.name }}</span>
        <span v-if="target" class="chat-inline-tool-target" :title="target">{{ target }}</span>
        <span class="chat-inline-tool-status" role="status">{{ toolStatusLabels[status] }}</span>
        <ChevronRight class="chat-inline-tool-chevron" :size="14" aria-hidden="true" />
      </summary>
      <div class="chat-inline-tool-details">
        <p v-if="activity.notice">{{ activity.notice }}</p>
        <h4>调用参数</h4>
        <pre tabindex="0" :aria-label="activity.name + ' 调用参数'">{{
          activity.argumentsText
        }}</pre>
        <template v-if="activity.resultText">
          <h4>{{ status === 'failed' ? '错误详情' : '调用结果' }}</h4>
          <p v-if="status === 'failed'" class="chat-tool-error-location">
            {{ activity.errorType || '工具调用失败' }}<span v-if="target"> · {{ target }}</span>
          </p>
          <pre ref="result" tabindex="0" :aria-label="activity.name + ' 调用结果'">{{
            activity.resultText
          }}</pre>
        </template>
        <p v-if="status === 'failed'" class="chat-tool-call-id">调用 ID：{{ activity.callId }}</p>
      </div>
    </details>
    <div v-if="summary || activity.notice" class="chat-tool-preview">
      <p>{{ summary || activity.notice }}</p>
      <button v-if="status === 'failed' && activity.resultText" type="button" @click="locateError">
        定位错误
      </button>
    </div>
    <ChatToolApproval
      v-if="approval"
      :approval="approval"
      @approve="$emit('approve', $event)"
      @deny="$emit('deny', $event)"
    />
  </article>
</template>
