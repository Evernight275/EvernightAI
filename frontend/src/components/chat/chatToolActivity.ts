import { computed, type ComputedRef } from 'vue'
import type {
  AgentRunState,
  AgentStep,
  AgentTraceEvent,
  ToolApprovalRequest,
} from '../../api'

export type ChatToolActivityProps = {
  run: AgentRunState | null
  trace: AgentTraceEvent[]
  pendingApprovals: ToolApprovalRequest[]
}

export type ChatToolActivityEntry = {
  key: string
  name: string
  status: 'completed' | 'failed' | 'approval required'
  statusLabel: string
  callText: string
  resultText: string | null
}

export function useChatToolActivity(
  props: ChatToolActivityProps,
): { activities: ComputedRef<ChatToolActivityEntry[]> } {
  return {
    activities: computed(() => toolActivities(
      props.run,
      props.trace,
      props.pendingApprovals,
    )),
  }
}

export function toolActivities(
  run: AgentRunState | null,
  trace: AgentTraceEvent[] = [],
  pendingApprovals: ToolApprovalRequest[] = [],
): ChatToolActivityEntry[] {
  const steps = run?.steps || traceSteps(trace)
  const activities: ChatToolActivityEntry[] = steps.flatMap((step, index) => {
    if (step.step_type !== 'tool' && step.step_type !== 'tool_error') {
      return []
    }
    return [{
      key: step.tool_call?.tool_call_id || `tool-${index}`,
      name: toolName(step),
      status: step.step_type === 'tool' ? 'completed' : 'failed',
      statusLabel: step.step_type === 'tool' ? '已完成' : '失败',
      callText: JSON.stringify(step.tool_call?.tool_call || {}, null, 2),
      resultText: step.error_message || (step.tool_result
        ? JSON.stringify(step.tool_result.tool_call_result, null, 2) : null),
    }]
  })
  const recordedIds = new Set(activities.map((activity) => activity.key))
  return [
    ...activities,
    ...pendingApprovals.flatMap((approval) => (
      recordedIds.has(approval.tool_call_id)
        ? []
        : [{
            key: approval.tool_call_id,
            name: approval.tool_name,
            status: 'approval required' as const,
            statusLabel: '等待审批',
            callText: JSON.stringify(approval.tool_call || {}, null, 2),
            resultText: null,
          }]
    )),
  ]
}

function traceSteps(trace: AgentTraceEvent[]): AgentStep[] {
  const steps: AgentStep[] = []
  trace.forEach((event) => {
    if (event.event_type === 'tool_completed') {
      steps.push({ step_type: 'tool', tool_call: event.tool_call, tool_result: event.tool_result })
      return
    }
    if (event.event_type === 'tool_failed') {
      steps.push({
        step_type: 'tool_error',
        tool_call: event.tool_call,
        error_message: event.error_message,
      })
    }
  })
  return steps
}

function toolName(step: AgentStep): string {
  const name = step.tool_call?.tool_call.name
  return typeof name === 'string' && name ? name : '[unknown tool]'
}
