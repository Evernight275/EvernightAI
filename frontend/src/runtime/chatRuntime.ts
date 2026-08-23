import {
  cancelAgentRun,
  createContext,
  deleteContext,
  getAgentRun,
  resumeAgentRunStream,
  retryAgentRunStream,
  startAgentRunStream,
  type AgentRunState,
  type AgentTraceEvent,
  type ToolApprovalDecision,
  type ToolApprovalStatus,
  type ToolDefinition,
} from '../api'
import type { ChatSubmission } from '../domain/chat'

const maxToolRounds = 4

export type ChatRequestInput = {
  contextId: string
  submission: ChatSubmission
  tools: ToolDefinition[]
  runId?: string
  onTrace?: (event: AgentTraceEvent) => void
}

export type ChatResumeInput = {
  run: AgentRunState
  approvalStatuses: ApprovalStatuses
  onTrace?: (event: AgentTraceEvent) => void
}

export type ApprovalStatuses = Record<
  string,
  Extract<ToolApprovalStatus, 'approved' | 'denied'>
>

export type ChatRetryInput = {
  run: AgentRunState
  runId: string
  onTrace?: (event: AgentTraceEvent) => void
}

export type ChatCancelInput = {
  run: AgentRunState | null
  runId?: string | null
}

export type ChatClearInput = {
  contextId: string | null
  run: AgentRunState | null
  runId?: string | null
}

export function createChatContextId(): string {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `web-chat-${suffix}`
}

export function createChatRunId(): string {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `web-run-${suffix}`
}

export async function prepareChatContext(
  contextId: string,
  signal: AbortSignal,
): Promise<void> {
  await createContext({ context_id: contextId, messages: [] }, signal)
}

export async function streamChatRun(
  input: ChatRequestInput,
  signal: AbortSignal,
): Promise<AgentRunState> {
  const runId = input.runId || createChatRunId()
  const request = agentRunRequest(input, {
    run_id: runId,
    stream: true,
  })
  return streamAndReadRun(
    runId,
    () => startAgentRunStream(request, (event) => input.onTrace?.(event), signal),
    signal,
  )
}

export async function resumeChatRunStream(
  input: ChatResumeInput,
  signal: AbortSignal,
): Promise<AgentRunState> {
  return streamAndReadRun(
    input.run.run_id,
    () => resumeAgentRunStream(input.run.run_id, {
      approvals: approvalDecisions(input.run, input.approvalStatuses),
    }, (event) => input.onTrace?.(event), signal),
    signal,
  )
}

export function retryChatRun(
  input: ChatRetryInput,
  signal: AbortSignal,
): Promise<AgentRunState> {
  return retryChatRunStream(input, signal)
}

async function retryChatRunStream(
  input: ChatRetryInput,
  signal: AbortSignal,
): Promise<AgentRunState> {
  return streamAndReadRun(
    input.runId,
    () => retryAgentRunStream(input.run.run_id, {
      retried_run_id: input.runId,
    }, (event) => input.onTrace?.(event), signal),
    signal,
  )
}

export async function cancelChatRun(
  input: ChatCancelInput,
  signal: AbortSignal,
): Promise<AgentRunState | null> {
  const runId = input.runId || input.run?.run_id
  if (!runId) {
    return null
  }
  return cancelAgentRun(runId, { reason: 'user canceled chat' }, signal)
}

export async function clearChatContext(
  input: ChatClearInput,
  signal: AbortSignal,
): Promise<void> {
  const runId = input.runId || input.run?.run_id
  const shouldCancel = runId && (
    !input.run
    || input.run.run_id !== runId
    || input.run.status === 'running'
    || input.run.status === 'paused'
  )
  if (shouldCancel) {
    try {
      await cancelAgentRun(runId, { reason: 'chat history cleared' }, signal)
    } catch {
      // Context cleanup remains the important part when the run is already terminal.
    }
  }
  if (input.contextId) {
    await deleteContext(input.contextId, signal)
  }
}

export function approvalDecisions(
  run: AgentRunState,
  statuses: ApprovalStatuses,
): ToolApprovalDecision[] {
  const pending = run.pending_approval_requests || []
  return pending.map((request) => {
    const status = statuses[request.approval_id]
    if (!status) {
      throw new Error(`Missing decision for tool approval: ${request.approval_id}`)
    }
    return {
      approval_id: request.approval_id,
      tool_call_id: request.tool_call_id,
      status,
    }
  })
}

async function streamAndReadRun(
  runId: string,
  stream: () => Promise<void>,
  signal: AbortSignal,
): Promise<AgentRunState> {
  try {
    await stream()
  } catch (streamError) {
    if (!signal.aborted) {
      try {
        return await getAgentRun(runId, signal)
      } catch {
        // Preserve the transport error when no persisted run can be recovered.
      }
    }
    throw streamError
  }
  return getAgentRun(runId, signal)
}

function agentRunRequest(
  input: ChatRequestInput,
  metadata: Record<string, unknown> = {},
) {
  return {
    provider_id: input.submission.providerId,
    context_id: input.contextId,
    model_id: input.submission.modelId,
    messages: [{
      role: 'user' as const,
      content: [{ type: 'text', text: input.submission.text }],
    }],
    tools: input.tools,
    max_tool_rounds: maxToolRounds,
    recover_tool_errors: true,
    write_memory: false,
    pause_on_approval: true,
    metadata,
  }
}
