<script setup lang="ts">
import { Play, RotateCcw } from '@lucide/vue'
import ChatToolApproval from './ChatToolApproval.vue'
import {
  useChatRequestStatus,
  type ChatRequestStatusEmits,
  type ChatRequestStatusProps,
} from './chatRequestStatus'

const props = defineProps<ChatRequestStatusProps>()
defineEmits<ChatRequestStatusEmits>()
const {
  visible,
  errorMessage,
  approvalItems,
  canRetry,
  canResume,
} = useChatRequestStatus(props)
</script>

<template>
  <section v-if="visible" class="chat-request-status" aria-label="待处理事项">
    <div v-if="errorMessage || canRetry" class="chat-notice">
      <p class="chat-status-error" role="alert">{{ errorMessage || '运行失败' }}</p>
      <button v-if="canRetry" type="button" @click="$emit('retry')">
        <RotateCcw :size="16" aria-hidden="true" /> 重试
      </button>
      <button type="button" @click="$emit('details')">查看详情</button>
    </div>
    <div v-if="workspaceNotice" class="chat-notice">
      <p role="status">{{ workspaceNotice }}</p>
      <button type="button" @click="$emit('details')">查看详情</button>
    </div>
    <div v-if="canResume" class="chat-notice">
      <p role="status">运行已暂停</p>
      <button type="button" @click="$emit('resume')">
        <Play :size="16" aria-hidden="true" /> 继续运行
      </button>
    </div>
    <details v-if="approvalItems.length > 0" class="chat-approval-group" open>
      <summary>等待工具审批（{{ approvalItems.length }}）</summary>
      <div class="chat-approval-list">
        <ChatToolApproval
          v-for="approval in approvalItems"
          :key="approval.approval_id"
          :approval="approval"
          @approve="$emit('approve', $event)"
          @deny="$emit('deny', $event)"
        />
      </div>
    </details>
  </section>
</template>
