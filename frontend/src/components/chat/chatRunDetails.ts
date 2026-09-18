import { computed } from 'vue'
import type {
  AgentRunState,
  AgentTraceEvent,
  ToolApprovalRequest,
} from '../../api'
import type { WorkspaceIssue } from '../../domain/workspace'
import { useDialog } from '../common/dialog'
import { formatChatError, formatChatState } from './chatRequestStatus'

export type ChatRunDetailsProps = {
  open: boolean
  workspaceState: string
  chatState: string
  workspaceIssues: WorkspaceIssue[]
  providerCount: number
  toolCount: number
  error: unknown
  hasTranscript: boolean
  busy: boolean
  run: AgentRunState | null
  trace: AgentTraceEvent[]
  runId: string | null
  pendingApprovals: ToolApprovalRequest[]
}

export type ChatRunDetailsEmits = {
  clear: []
  close: []
}

export function useChatRunDetails(props: ChatRunDetailsProps, close: () => void) {
  return {
    ...useDialog(() => props.open, close),
    stateLabel: computed(() => formatChatState(props.chatState)),
    errorMessage: computed(() => formatChatError(props.error)),
    requestText: computed(() => JSON.stringify(props.run?.request || null, null, 2)),
    traceText: computed(() => JSON.stringify(props.trace.length ? props.trace : props.run?.trace || [], null, 2)),
  }
}
