import { requestJson, requestSse, type SseEvent } from './client'
import type { ChatResponse, ChatSkill, Content } from './content'
import type { MemoryQuery } from './memory'
import type {
  ToolApprovalDecision,
  ToolApprovalRequest,
  ToolCall,
  ToolCallResult,
  ToolDefinition,
} from './tools'

export type AgentStepType = 'start' | 'chat' | 'tool' | 'tool_error' | 'memory_write' | 'stop'

export type AgentTraceEventType =
  | 'run_started'
  | 'chat_delta'
  | 'chat_completed'
  | 'tool_approval_requested'
  | 'tool_approval_decided'
  | 'tool_completed'
  | 'tool_failed'
  | 'memory_written'
  | 'run_paused'
  | 'run_stopped'

export type AgentRunStatus = 'running' | 'paused' | 'canceled' | 'finished' | 'failed'
export type AgentStopReason = 'finished' | 'tool_rounds_exhausted' | 'tool_error'

export type AgentRunRequest = {
  provider_id: string
  context_id: string
  model_id: string
  messages?: Content[]
  retry_from_message_index?: number | null
  memory_query?: MemoryQuery | null
  skills?: ChatSkill[] | null
  tools?: ToolDefinition[] | null
  max_tool_rounds?: number
  recover_tool_errors?: boolean
  write_memory?: boolean
  tool_approvals?: ToolApprovalDecision[]
  pause_on_approval?: boolean
  metadata?: Record<string, unknown>
}

export type AgentStep = {
  step_type: AgentStepType
  response?: ChatResponse | null
  message?: Content | null
  tool_call?: ToolCall | null
  tool_result?: ToolCallResult | null
  error_type?: string | null
  error_message?: string | null
  metadata?: Record<string, unknown>
}

export type AgentTraceEvent = {
  sequence?: number | null
  event_type: AgentTraceEventType
  summary?: string | null
  step_type?: AgentStepType | null
  message?: Content | null
  response?: ChatResponse | null
  text_delta?: string | null
  tool_call?: ToolCall | null
  tool_result?: ToolCallResult | null
  approval_request?: ToolApprovalRequest | null
  approval_decision?: ToolApprovalDecision | null
  error_type?: string | null
  error_message?: string | null
  metadata?: Record<string, unknown>
}

export type AgentRunState = {
  run_id: string
  request: AgentRunRequest
  status?: AgentRunStatus | string
  response?: ChatResponse | null
  stop_reason?: AgentStopReason | string | null
  steps?: AgentStep[]
  trace?: AgentTraceEvent[]
  remaining_tool_rounds?: number
  tool_rounds_used?: number
  pending_tool_calls?: ToolCall[]
  pending_approval_requests?: ToolApprovalRequest[]
  metadata?: Record<string, unknown>
}

export type ResumeAgentRunRequest = {
  approvals: ToolApprovalDecision[]
}

export function startAgentRun(request: AgentRunRequest): Promise<AgentRunState> {
  return requestJson<AgentRunState>('/agent-runs', {
    method: 'POST',
    body: request,
  })
}

export function startAgentRunStream(
  request: AgentRunRequest,
  onEvent: (event: AgentTraceEvent, rawEvent: SseEvent) => void,
): Promise<void> {
  return requestSse('/agent-runs/stream', {
    method: 'POST',
    body: request,
  }, (rawEvent) => {
    const event = agentTraceEventFromSse(rawEvent)
    if (event) {
      onEvent(event, rawEvent)
    }
  })
}

export function listAgentRuns(): Promise<AgentRunState[]> {
  return requestJson<AgentRunState[]>('/agent-runs')
}

export function getAgentRun(runId: string): Promise<AgentRunState> {
  return requestJson<AgentRunState>(`/agent-runs/${encodeURIComponent(runId)}`)
}

export function resumeAgentRun(
  runId: string,
  request: ResumeAgentRunRequest,
): Promise<AgentRunState> {
  return requestJson<AgentRunState>(`/agent-runs/${encodeURIComponent(runId)}/resume`, {
    method: 'POST',
    body: request,
  })
}

export function approvePendingAgentRun(runId: string): Promise<AgentRunState> {
  return requestJson<AgentRunState>(`/agent-runs/${encodeURIComponent(runId)}/approve-pending`, {
    method: 'POST',
  })
}

export function retryAgentRun(runId: string): Promise<AgentRunState> {
  return requestJson<AgentRunState>(`/agent-runs/${encodeURIComponent(runId)}/retry`, {
    method: 'POST',
  })
}

export function listAgentTrace(
  runId: string,
  options: { afterSequence?: number; limit?: number } = {},
): Promise<AgentTraceEvent[]> {
  const query = new URLSearchParams()
  if (options.afterSequence !== undefined) {
    query.set('after_sequence', String(options.afterSequence))
  }
  if (options.limit !== undefined) {
    query.set('limit', String(options.limit))
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : ''
  return requestJson<AgentTraceEvent[]>(
    `/agent-runs/${encodeURIComponent(runId)}/trace${suffix}`,
  )
}

function agentTraceEventFromSse(rawEvent: SseEvent): AgentTraceEvent | null {
  if (rawEvent.data === '[DONE]' || rawEvent.data.trim() === '') {
    return null
  }

  const payload = parseSseJson(rawEvent)
  if (rawEvent.event === 'error') {
    const error = isRecord(payload.error) ? payload.error : payload
    throw new Error(
      typeof error.message === 'string'
        ? error.message
        : 'Agent 流式响应失败',
    )
  }

  if (!isRecord(payload)) {
    return null
  }

  const event = payload as AgentTraceEvent
  if (!event.event_type && isAgentTraceEventType(rawEvent.event)) {
    event.event_type = rawEvent.event
  }

  return event.event_type ? event : null
}

function parseSseJson(rawEvent: SseEvent): Record<string, unknown> {
  try {
    const parsed = JSON.parse(rawEvent.data) as unknown
    return isRecord(parsed) ? parsed : {}
  } catch {
    throw new Error(`无法解析 Agent 流式事件：${rawEvent.event}`)
  }
}

function isAgentTraceEventType(value: string): value is AgentTraceEventType {
  return [
    'run_started',
    'chat_delta',
    'chat_completed',
    'tool_approval_requested',
    'tool_approval_decided',
    'tool_completed',
    'tool_failed',
    'memory_written',
    'run_paused',
    'run_stopped',
  ].includes(value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
