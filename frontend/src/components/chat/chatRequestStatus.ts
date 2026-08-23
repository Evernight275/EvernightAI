import { computed, type ComputedRef } from 'vue'
import type { ToolApprovalRequest, ToolApprovalStatus } from '../../api'
import type { ApprovalStatuses } from '../../runtime/chatRuntime'

export type ChatRequestStatusProps = {
  state: string
  error: unknown
  hasTranscript: boolean
  runId: string | null
  pendingApprovals: ToolApprovalRequest[]
  approvalStatuses: ApprovalStatuses
  cancelableRun: boolean
}

export type ChatRequestStatusEmits = {
  retry: []
  clear: []
  approve: [approvalId: string]
  deny: [approvalId: string]
  resume: []
  cancel: []
}

export function useChatRequestStatus(
  props: ChatRequestStatusProps,
): {
  errorMessage: ComputedRef<string | null>
  approvalItems: ComputedRef<ChatApprovalItem[]>
  canRetry: ComputedRef<boolean>
  canResume: ComputedRef<boolean>
  canClear: ComputedRef<boolean>
  canCancel: ComputedRef<boolean>
} {
  return {
    errorMessage: computed(() => formatChatError(props.error)),
    approvalItems: computed(() => props.state === 'approvalRequired'
      ? props.pendingApprovals.map((approval) => approvalItem(
        approval,
        props.approvalStatuses[approval.approval_id],
      ))
      : []),
    canRetry: computed(() => props.state === 'failed'),
    canResume: computed(() => props.state === 'resumeRequired'),
    canClear: computed(() => props.hasTranscript),
    canCancel: computed(() => props.cancelableRun || [
      'preparing',
      'streaming',
      'approvalRequired',
      'resumeRequired',
      'resuming',
      'retrying',
    ].includes(props.state)),
  }
}

export type ChatApprovalItem = ToolApprovalRequest & {
  toolCallText: string
  permissionsText: string
  decisionText: string | null
}

export function approvalItem(
  approval: ToolApprovalRequest,
  status?: Extract<ToolApprovalStatus, 'approved' | 'denied'>,
): ChatApprovalItem {
  return {
    ...approval,
    toolCallText: JSON.stringify(approval.tool_call || {}, null, 2),
    permissionsText: approval.permissions?.join(', ') || '无',
    decisionText: status === 'approved'
      ? '已批准'
      : status === 'denied' ? '已拒绝' : null,
  }
}

export function formatChatError(error: unknown): string | null {
  if (!error) {
    return null
  }
  return error instanceof Error ? error.message : String(error)
}
