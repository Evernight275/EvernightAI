import type {
  AgentRunState,
  AgentTraceEvent,
  ToolApprovalRequest,
} from '../../api'
import type { WorkspaceIssue } from '../../domain/workspace'
import type { ApprovalStatuses } from '../../runtime/chatRuntime'

export type ChatRunDetailsProps = {
  open: boolean
  workspaceState: string
  chatState: string
  workspaceIssues: WorkspaceIssue[]
  providerCount: number
  toolCount: number
  error: unknown
  hasTranscript: boolean
  run: AgentRunState | null
  trace: AgentTraceEvent[]
  runId: string | null
  pendingApprovals: ToolApprovalRequest[]
  approvalStatuses: ApprovalStatuses
  cancelableRun: boolean
}

export type ChatRunDetailsEmits = {
  retry: []
  clear: []
  approve: [approvalId: string]
  deny: [approvalId: string]
  resume: []
  cancel: []
}
