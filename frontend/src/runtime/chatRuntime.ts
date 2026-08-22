import {
  cancelAgentRun,
  createContext,
  deleteContext,
  getAgentRun,
  resumeAgentRunStream,
  retryAgentRun,
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
  status: Extract<ToolApprovalStatus, 'approved' | 'denied'>
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
  await startAgentRunStream(request, (event) => input.onTrace?.(event), signal)
  return getAgentRun(runId, signal)
}

export async function resumeChatRunStream(
  input: ChatResumeInput,
  signal: AbortSignal,
  onTrace?: (event: AgentTraceEvent) => void,
): Promise<AgentRunState> {
  await resumeAgentRunStream(input.run.run_id, {
    approvals: approvalDecisions(input.run, input.status),
  }, (event) => onTrace?.(event), signal)
  return getAgentRun(input.run.run_id, signal)
}

export function retryChatRun(
  run: AgentRunState,
  signal: AbortSignal,
): Promise<AgentRunState> {
  return retryAgentRun(run.run_id, signal)
}

export async function cancelChatRun(
  input: ChatCancelInput,
  signal: AbortSignal,
): Promise<AgentRunState | null> {
  const runId = input.run?.run_id || input.runId
  if (!runId) {
    return null
  }
  return cancelAgentRun(runId, { reason: 'user canceled chat' }, signal)
}

export async function clearChatContext(
  input: ChatClearInput,
  signal: AbortSignal,
): Promise<void> {
  const runId = input.run?.run_id || input.runId
  if (runId && (!input.run || input.run.status === 'running' || input.run.status === 'paused')) {
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
  status: Extract<ToolApprovalStatus, 'approved' | 'denied'>,
): ToolApprovalDecision[] {
  return (run.pending_approval_requests || []).map((request) => ({
    approval_id: request.approval_id,
    tool_call_id: request.tool_call_id,
    status,
  }))
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
