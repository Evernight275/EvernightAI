import { computed, type ComputedRef } from 'vue'
import type { AgentRunState, AgentTraceEvent, ToolApprovalRequest } from '../../api'
import {
  reconcileRunTranscript,
  toolStatusLabels,
  type ChatTranscriptEntry,
} from '../../domain/chat'

export type ChatToolActivityProps = {
  run: AgentRunState | null
  trace: AgentTraceEvent[]
  pendingApprovals: ToolApprovalRequest[]
}

export type ChatToolActivityEntry = {
  key: string
  name: string
  status: NonNullable<ChatTranscriptEntry['toolActivity']>['status']
  statusLabel: string
  callText: string
  resultText: string | null
}

export function useChatToolActivity(props: ChatToolActivityProps): {
  activities: ComputedRef<ChatToolActivityEntry[]>
} {
  return {
    activities: computed(() => toolActivities(props.run, props.trace, props.pendingApprovals)),
  }
}

export function toolActivities(
  run: AgentRunState | null,
  trace: AgentTraceEvent[] = [],
  pendingApprovals: ToolApprovalRequest[] = [],
): ChatToolActivityEntry[] {
  const snapshot: AgentRunState = {
    run_id: 'details',
    request: { provider_id: '', model_id: '', context_id: '' },
    ...run,
    status:
      run?.status === 'paused' &&
      trace.length &&
      !['run_paused', 'run_stopped'].includes(trace.at(-1)!.event_type)
        ? 'running'
        : run?.status,
    trace: trace.length ? trace : run?.trace,
    pending_approval_requests: pendingApprovals.length
      ? pendingApprovals
      : run?.pending_approval_requests,
  }
  return reconcileRunTranscript([], snapshot).flatMap((entry) => {
    const activity = entry.toolActivity
    return activity
      ? [
          {
            key: activity.callId,
            name: activity.name,
            status: activity.status,
            statusLabel: toolStatusLabels[activity.status],
            callText: activity.argumentsText,
            resultText: activity.resultText || null,
          },
        ]
      : []
  })
}
