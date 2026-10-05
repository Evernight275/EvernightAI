<script setup lang="ts">
import { computed, nextTick, ref } from 'vue';
import { Check, ChevronRight, CircleAlert, Clock, LoaderCircle, Wrench } from '@lucide/vue';
import { toolStatusLabels, type ChatTranscriptEntry } from '../../domain/chat';
import type { ChatApprovalItem } from './chatRequestStatus';
import ChatToolApproval from './ChatToolApproval.vue';
import { imageToolRecordId, toolResultSummary } from './toolResult';
import ChatImageResult from './ChatImageResult.vue';
import ChatToolDisplay from './ChatToolDisplay.vue';
import JsonCode from '../common/JsonCode.vue';
import ToolOutput from '../common/ToolOutput.vue';
import ToolDuration from './ToolDuration.vue';

const props = defineProps<{
  activity: NonNullable<ChatTranscriptEntry['toolActivity']>;
  approval?: ChatApprovalItem;
}>();
defineEmits<{ approve: [approvalId: string]; deny: [approvalId: string] }>();
const details = ref<HTMLDetailsElement>();
const result = ref<HTMLPreElement>();
const resultOutput = ref<InstanceType<typeof ToolOutput>>();
const status = computed(() =>
  props.approval?.decisionText === '已拒绝'
    ? 'failed'
    : props.approval?.decisionText === '已批准'
      ? 'pending'
      : props.activity.status,
);
const summary = computed(() => toolResultSummary(props.activity.resultText));
const imageRecordId = computed(() => imageToolRecordId(props.activity.resultText));
const target = computed(() => {
  try {
    const args = JSON.parse(props.activity.argumentsText);
    const command =
      Array.isArray(args.command) && args.command.every((part: unknown) => typeof part === 'string')
        ? args.command.join(' ')
        : args.command;
    const path =
      [args.path, args.file_path, args.directory, command, args.task, args.query, args.url].find(
        (value) => typeof value === 'string',
      ) || '';
    const line = args.line ?? args.start_line;
    return path && Number.isInteger(line) ? `${path}:${line}` : path;
  } catch {
    return '';
  }
});
async function locateError() {
  if (details.value) details.value.open = true;
  await nextTick();
  await resultOutput.value?.expand();
  result.value?.focus({ preventScroll: true });
  result.value?.scrollIntoView({ block: 'nearest', behavior: 'auto' });
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
        <ToolDuration
          :started-at="activity.startedAt"
          :finished-at="activity.finishedAt"
          :duration-ms="activity.durationMs"
          :running="status === 'running'"
        />
        <span class="chat-inline-tool-status" role="status">{{ toolStatusLabels[status] }}</span>
        <ChevronRight class="chat-inline-tool-chevron" :size="14" aria-hidden="true" />
      </summary>
      <div class="chat-inline-tool-details">
        <p v-if="activity.notice">{{ activity.notice }}</p>
        <h4>调用参数</h4>
        <ToolOutput :source="activity.argumentsText" :label="activity.name + ' 调用参数'">
          <pre
            tabindex="0"
            :aria-label="activity.name + ' 调用参数'"
          ><JsonCode :source="activity.argumentsText" /></pre>
        </ToolOutput>
        <template v-if="activity.resultText">
          <h4>{{ status === 'failed' ? '错误详情' : '调用结果' }}</h4>
          <p v-if="status === 'failed'" class="chat-tool-error-location">
            {{ activity.errorType || '工具调用失败' }}<span v-if="target"> · {{ target }}</span>
          </p>
          <ToolOutput
            ref="resultOutput"
            :source="activity.resultText"
            :label="activity.name + ' 调用结果'"
          >
            <pre
              ref="result"
              tabindex="0"
              :aria-label="activity.name + ' 调用结果'"
            ><JsonCode :source="activity.resultText" /></pre>
          </ToolOutput>
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
    <ChatToolDisplay
      v-if="status === 'completed'"
      :name="activity.name"
      :result-text="activity.resultText"
    />
    <ChatImageResult v-if="status === 'completed' && imageRecordId" :record-id="imageRecordId" />
    <ChatToolApproval
      v-if="approval"
      :approval="approval"
      @approve="$emit('approve', $event)"
      @deny="$emit('deny', $event)"
    />
  </article>
</template>
