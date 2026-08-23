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
  awaitingApproval,
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
    <div v-if="awaitingApproval">
      <h3>等待工具审批</h3>
      <ul>
        <li v-for="approval in pendingApprovals" :key="approval.approval_id">
          {{ approval.tool_name }} / {{ approval.safety_level }}
          <span v-if="approval.reason"> / {{ approval.reason }}</span>
        </li>
      </ul>
      <button type="button" @click="$emit('approve')">批准</button>
      <button type="button" @click="$emit('deny')">拒绝</button>
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
