import { computed, type ComputedRef } from 'vue'
import type { ToolApprovalRequest } from '../../api'

export type ChatRequestStatusProps = {
  state: string
  error: unknown
  hasTranscript: boolean
  runId: string | null
  pendingApprovals: ToolApprovalRequest[]
}

export type ChatRequestStatusEmits = {
  retry: []
  clear: []
  approve: []
  deny: []
  resume: []
  cancel: []
}

export function useChatRequestStatus(
  props: ChatRequestStatusProps,
): {
  errorMessage: ComputedRef<string | null>
  awaitingApproval: ComputedRef<boolean>
  canRetry: ComputedRef<boolean>
  canResume: ComputedRef<boolean>
  canClear: ComputedRef<boolean>
  canCancel: ComputedRef<boolean>
} {
  return {
    errorMessage: computed(() => formatChatError(props.error)),
    awaitingApproval: computed(() => (
      props.state === 'approvalRequired' && props.pendingApprovals.length > 0
    )),
    canRetry: computed(() => props.state === 'failed'),
    canResume: computed(() => props.state === 'resumeRequired'),
    canClear: computed(() => props.hasTranscript),
    canCancel: computed(() => [
      'preparing',
      'streaming',
      'approvalRequired',
      'resumeRequired',
      'resuming',
      'retrying',
    ].includes(props.state)),
  }
}

export function formatChatError(error: unknown): string | null {
  if (!error) {
    return null
  }
  return error instanceof Error ? error.message : String(error)
}
