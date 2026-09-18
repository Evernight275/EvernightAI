<script setup lang="ts">
import { Trash2, X } from '@lucide/vue'
import ChatPrerequisites from './ChatPrerequisites.vue'
import ChatToolActivity from './ChatToolActivity.vue'
import {
  useChatRunDetails,
  type ChatRunDetailsEmits,
  type ChatRunDetailsProps,
} from './chatRunDetails'

const props = defineProps<ChatRunDetailsProps>()
const emit = defineEmits<ChatRunDetailsEmits>()
const {
  setDialog,
  onCancel,
  onBackdropClick,
  onKeydown,
  stateLabel,
  errorMessage,
  requestText,
  traceText,
} = useChatRunDetails(props, () => emit('close'))
</script>

<template>
  <dialog id="chat-run-details" :ref="setDialog" class="chat-details-panel"
    aria-labelledby="chat-details-title" @cancel="onCancel" @click="onBackdropClick" @keydown="onKeydown">
    <header class="chat-panel-header">
      <h2 id="chat-details-title">运行详情</h2>
      <button class="icon-button" type="button" aria-label="关闭运行详情" title="关闭运行详情"
        autofocus @click="$emit('close')"><X :size="18" aria-hidden="true" /></button>
    </header>
    <div class="chat-details-content">
      <section>
        <h3>请求状态</h3>
        <p>{{ stateLabel }}</p>
        <p v-if="runId" class="chat-run-id">运行 ID：<code>{{ runId }}</code></p>
        <p v-if="errorMessage" class="chat-status-error">{{ errorMessage }}</p>
      </section>
      <ChatToolActivity :run="run" :trace="trace" :pending-approvals="pendingApprovals" />
      <section>
        <h3>诊断信息</h3>
        <ChatPrerequisites
          :state="workspaceState"
          :provider-count="providerCount"
          :tool-count="toolCount"
          :issues="workspaceIssues"
        />
      </section>
      <details class="chat-raw-details">
        <summary>原始请求参数</summary>
        <pre tabindex="0" aria-label="原始请求参数">{{ requestText }}</pre>
      </details>
      <details class="chat-raw-details">
        <summary>原始运行事件</summary>
        <pre tabindex="0" aria-label="原始运行事件">{{ traceText }}</pre>
      </details>
    </div>
    <footer v-if="hasTranscript" class="chat-panel-footer">
      <button class="button-danger" type="button" :disabled="busy" @click="$emit('clear')">
        <Trash2 :size="16" aria-hidden="true" /> 清空对话记录
      </button>
    </footer>
  </dialog>
</template>
