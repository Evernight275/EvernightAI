<script setup lang="ts">
import {
  useChatRequestStatus,
  type ChatRequestStatusEmits,
  type ChatRequestStatusProps,
} from './chatRequestStatus'

const props = defineProps<ChatRequestStatusProps>()
defineEmits<ChatRequestStatusEmits>()
const {
  errorMessage,
  approvalItems,
  canRetry,
  canResume,
  canClear,
  canCancel,
} = useChatRequestStatus(props)
</script>

<template>
  <section>
    <h2>请求状态</h2>
    <p>{{ state }}</p>
    <p v-if="runId">Agent run：{{ runId }}</p>
    <p v-if="errorMessage">{{ errorMessage }}</p>
    <div v-if="approvalItems.length > 0">
      <h3>等待工具审批</h3>
      <ul>
        <li v-for="approval in approvalItems" :key="approval.approval_id">
          {{ approval.tool_name }} / {{ approval.safety_level }}
          <span v-if="approval.reason"> / {{ approval.reason }}</span>
          <p>权限：{{ approval.permissionsText }}</p>
          <pre>{{ approval.toolCallText }}</pre>
          <p v-if="approval.decisionText">{{ approval.decisionText }}</p>
          <button
            type="button"
            @click="$emit('approve', approval.approval_id)"
          >
            批准此项
          </button>
          <button
            type="button"
            @click="$emit('deny', approval.approval_id)"
          >
            拒绝此项
          </button>
        </li>
      </ul>
    </div>
    <button v-if="canRetry" type="button" @click="$emit('retry')">
      重试
    </button>
    <button v-if="canResume" type="button" @click="$emit('resume')">
      继续运行
    </button>
    <button v-if="canCancel" type="button" @click="$emit('cancel')">
      取消当前运行
    </button>
    <button v-if="canClear" type="button" @click="$emit('clear')">
      清空对话记录
    </button>
  </section>
</template>
