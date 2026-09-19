<script setup lang="ts">
import { Activity, ChevronRight, Code2, Trash2, X } from '@lucide/vue'
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
  <dialog
    id="chat-run-details"
    :ref="setDialog"
    class="chat-details-panel"
    aria-labelledby="chat-details-title"
    @cancel="onCancel"
    @click="onBackdropClick"
    @keydown="onKeydown"
  >
    <header class="chat-panel-header">
      <div class="chat-panel-heading">
        <span class="chat-panel-symbol"><Activity :size="18" aria-hidden="true" /></span>
        <div>
          <h2 id="chat-details-title">运行详情</h2>
          <p>查看本次请求与工具执行情况</p>
        </div>
      </div>
      <button
        class="icon-button"
        type="button"
        aria-label="关闭运行详情"
        title="关闭运行详情"
        autofocus
        @click="$emit('close')"
      >
        <X :size="18" aria-hidden="true" />
      </button>
    </header>
    <div class="chat-details-content">
      <section class="chat-run-overview">
        <div class="chat-run-status-heading">
          <h3>请求状态</h3>
          <span class="chat-run-badge" :class="{ 'is-active': busy, 'is-error': !!errorMessage }"
            ><span aria-hidden="true"></span>{{ stateLabel }}</span
          >
        </div>
        <p class="chat-run-description">
          {{
            busy
              ? '请求正在进行，执行信息会实时更新。'
              : runId
                ? '本次请求的执行记录与诊断信息。'
                : '发送消息后，可在这里查看执行过程。'
          }}
        </p>
        <p v-if="run?.request.working_directory" class="chat-run-id">
          工作文件夹：<code>{{ run.request.working_directory }}</code>
        </p>
        <p v-if="runId" class="chat-run-id">
          运行 ID：<code>{{ runId }}</code>
        </p>
        <p v-if="errorMessage" class="chat-status-error">{{ errorMessage }}</p>
      </section>
      <ChatToolActivity
        :run="run?.run_id === runId ? run : null"
        :trace="trace"
        :pending-approvals="pendingApprovals"
      />
      <details class="chat-diagnostic-details" :open="workspaceIssues.length > 0">
        <summary><span>环境与诊断</span><ChevronRight :size="16" aria-hidden="true" /></summary>
        <ChatPrerequisites
          :state="workspaceState"
          :provider-count="providerCount"
          :tool-count="toolCount"
          :issues="workspaceIssues"
        />
      </details>
      <section class="chat-run-advanced">
        <h3><Code2 :size="15" aria-hidden="true" /> 开发者信息</h3>
        <details class="chat-raw-details">
          <summary>原始请求参数</summary>
          <pre tabindex="0" aria-label="原始请求参数">{{ requestText }}</pre>
        </details>
        <details class="chat-raw-details">
          <summary>原始运行事件</summary>
          <pre tabindex="0" aria-label="原始运行事件">{{ traceText }}</pre>
        </details>
      </section>
    </div>
    <footer v-if="hasTranscript" class="chat-panel-footer">
      <button class="button-danger" type="button" :disabled="busy" @click="$emit('clear')">
        <Trash2 :size="16" aria-hidden="true" /> 清空对话记录
      </button>
    </footer>
  </dialog>
</template>
