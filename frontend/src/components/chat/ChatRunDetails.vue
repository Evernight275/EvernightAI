<script setup lang="ts">
import ChatPrerequisites from './ChatPrerequisites.vue'
import ChatRequestStatus from './ChatRequestStatus.vue'
import ChatToolActivity from './ChatToolActivity.vue'
import type {
  ChatRunDetailsEmits,
  ChatRunDetailsProps,
} from './chatRunDetails'

defineProps<ChatRunDetailsProps>()
defineEmits<ChatRunDetailsEmits>()
</script>

<template>
  <details class="chat-details" :open="open">
    <summary>运行详情</summary>
    <div class="chat-details-content">
      <ChatPrerequisites
        :state="workspaceState"
        :provider-count="providerCount"
        :tool-count="toolCount"
        :issues="workspaceIssues"
      />

      <ChatToolActivity :run="run" :trace="trace" />

      <ChatRequestStatus
        :state="chatState"
        :error="error"
        :has-transcript="hasTranscript"
        :run-id="runId"
        :pending-approvals="pendingApprovals"
        :approval-statuses="approvalStatuses"
        :cancelable-run="cancelableRun"
        @retry="$emit('retry')"
        @clear="$emit('clear')"
        @cancel="$emit('cancel')"
        @approve="$emit('approve', $event)"
        @deny="$emit('deny', $event)"
        @resume="$emit('resume')"
      />
    </div>
  </details>
</template>
