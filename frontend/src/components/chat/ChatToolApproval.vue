<script setup lang="ts">
import { Check, X } from '@lucide/vue'
import type { ChatApprovalItem } from './chatRequestStatus'

defineProps<{
  approval: ChatApprovalItem
}>()

defineEmits<{
  approve: [approvalId: string]
  deny: [approvalId: string]
}>()
</script>

<template>
  <article class="chat-tool-approval">
    <header class="chat-approval-header">
      <strong>{{ approval.tool_name }}</strong>
      <span>{{ approval.safetyLabel }}</span>
    </header>
    <p v-if="approval.reason" class="chat-approval-reason">
      {{ approval.reason }}
    </p>
    <p class="chat-approval-permissions">
      权限：{{ approval.permissionsText }}
    </p>
    <dl v-if="approval.targets.length" class="chat-approval-targets">
      <div v-for="target in approval.targets" :key="target.name">
        <dt>{{ target.name }}</dt><dd tabindex="0">{{ target.value }}</dd>
      </div>
    </dl>
    <div class="chat-approval-actions">
      <button
        class="button-primary"
        type="button"
        :disabled="approval.decided"
        @click="$emit('approve', approval.approval_id)"
      >
        <Check :size="16" aria-hidden="true" />
        批准
      </button>
      <button
        class="button-danger"
        type="button"
        :disabled="approval.decided"
        @click="$emit('deny', approval.approval_id)"
      >
        <X :size="16" aria-hidden="true" />
        拒绝
      </button>
      <span v-if="approval.decisionText" class="chat-approval-decision">
        {{ approval.decisionText }}
      </span>
    </div>
    <details class="chat-approval-payload">
      <summary>查看调用参数</summary>
      <pre tabindex="0" :aria-label="approval.tool_name + ' 调用参数'">{{ approval.toolCallText }}</pre>
    </details>
  </article>
</template>
