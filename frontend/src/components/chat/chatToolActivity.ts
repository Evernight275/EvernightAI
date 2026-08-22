import { computed, type ComputedRef } from 'vue'
import type { AgentRunState, AgentStep } from '../../api'

export type ChatToolActivityProps = {
  run: AgentRunState | null
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
    activities: computed(() => toolActivities(props.run)),
  }
}

export function toolActivities(run: AgentRunState | null): ChatToolActivityEntry[] {
  return (run?.steps || []).flatMap((step, index) => {
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

function toolName(step: AgentStep): string {
  const name = step.tool_call?.tool_call.name
  return typeof name === 'string' && name ? name : '[unknown tool]'
}
