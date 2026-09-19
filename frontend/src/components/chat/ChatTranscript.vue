<script setup lang="ts">
import type { ToolApprovalRequest } from '../../api'
import type { ApprovalStatuses } from '../../runtime/chatRuntime'
import { approvalItem } from './chatRequestStatus'
import type { ChatTranscriptEntry } from '../../domain/chat'
import EmptyValue from '../common/EmptyValue.vue'
import ChatMessage from './ChatMessage.vue'
import ChatInlineTool from './ChatInlineTool.vue'
import { useChatTranscript } from './chatTranscript'

const props = defineProps<{
  entries: ChatTranscriptEntry[]
  runId?: string | null
  pendingApprovals?: ToolApprovalRequest[]
  approvalStatuses?: ApprovalStatuses
  canApprove?: boolean
}>()

defineEmits<{ approve: [approvalId: string]; deny: [approvalId: string] }>()
function inlineApproval(entry: ChatTranscriptEntry) {
  if (entry.streamRunId !== props.runId) return undefined
  const approval = props.pendingApprovals?.find(
    (item) => item.tool_call_id === entry.toolActivity?.callId,
  )
  if (!approval || !['approval', 'pending'].includes(entry.toolActivity?.status || ''))
    return undefined
  const item = approvalItem(approval, props.approvalStatuses?.[approval.approval_id])
  return { ...item, decided: item.decided || !props.canApprove }
}
const { setEndMarker } = useChatTranscript(() => props.entries)
</script>

<template>
  <section class="chat-transcript" aria-label="对话记录">
    <div v-if="!entries.length" class="chat-transcript-empty">
      <EmptyValue label="还没有消息" />
    </div>
    <ol v-else class="chat-transcript-list">
      <li
        v-for="entry in entries"
        :key="entry.entryId"
        :class="{ 'chat-transcript-tool': !!entry.toolActivity }"
      >
        <ChatInlineTool
          v-if="entry.toolActivity"
          :activity="entry.toolActivity"
          :approval="inlineApproval(entry)"
          @approve="$emit('approve', $event)"
          @deny="$emit('deny', $event)"
        />
        <ChatMessage v-else :entry="entry" />
      </li>
    </ol>
    <span :ref="setEndMarker" aria-hidden="true"></span>
  </section>
</template>
