import { computed, type ComputedRef } from 'vue'
import type { AgentRunState, AgentStep, AgentTraceEvent } from '../../api'

export type ChatToolActivityProps = {
  run: AgentRunState | null
  trace: AgentTraceEvent[]
}

export type ChatToolActivityEntry = {
  key: string
  name: string
  status: 'completed' | 'failed'
}

export function useChatToolActivity(
  props: ChatToolActivityProps,
): { activities: ComputedRef<ChatToolActivityEntry[]> } {
  return {
    activities: computed(() => toolActivities(props.run, props.trace)),
  }
}

export function toolActivities(
  run: AgentRunState | null,
  trace: AgentTraceEvent[] = [],
): ChatToolActivityEntry[] {
  const steps = run?.steps || traceSteps(trace)
  return steps.flatMap((step, index) => {
    if (step.step_type !== 'tool' && step.step_type !== 'tool_error') {
      return []
    }
    return [{
      key: step.tool_call?.tool_call_id || `tool-${index}`,
      name: toolName(step),
      status: step.step_type === 'tool' ? 'completed' : 'failed',
    }]
  })
}

function traceSteps(trace: AgentTraceEvent[]): AgentStep[] {
  const steps: AgentStep[] = []
  trace.forEach((event) => {
    if (event.event_type === 'tool_completed') {
      steps.push({ step_type: 'tool', tool_call: event.tool_call })
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
