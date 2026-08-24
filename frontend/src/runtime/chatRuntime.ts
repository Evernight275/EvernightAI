import {
  cancelAgentRun,
  createSession,
  createContext,
  deleteContext,
  getAgentRun,
  getContext,
  getSession,
  replaceContext,
  resumeAgentRunStream,
  retryAgentRunStream,
  startAgentRunStream,
  type AgentRunState,
  type AgentTraceEvent,
  type Session,
  type ToolApprovalDecision,
  type ToolApprovalStatus,
  type ToolDefinition,
} from '../api'
import {
  transcriptFromMessages,
  type ChatSubmission,
  type ChatTranscriptEntry,
} from '../domain/chat'

const maxToolRounds = 4

export type ChatRequestInput = {
  contextId: string
  sessionId?: string | null
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
  sessionId?: string | null
  run: AgentRunState | null
  runId?: string | null
}

export type ChatSessionInput = {
  session: Session
  currentRun: AgentRunState | null
  currentRunId: string | null
}

export type ChatSessionSnapshot = {
  session: Session
  transcript: ChatTranscriptEntry[]
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

export function createChatSessionId(): string {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `web-session-${suffix}`
}

export async function createChatSession(
  input: ChatSessionInput,
  signal: AbortSignal,
): Promise<ChatSessionSnapshot> {
  await cancelCurrentChatRun(input, signal)
  try {
    const session = await createSession(input.session, signal)
    return { session, transcript: [] }
  } catch (createError) {
    if (!signal.aborted) {
      try {
        const session = await getSession(input.session.session_id, signal)
        const context = await getContext(session.context_id, signal)
        return {
          session,
          transcript: transcriptFromMessages(context.messages || []),
        }
      } catch {
        // Preserve the create error when the requested session does not exist.
      }
    }
    throw createError
  }
}

export async function loadChatSession(
  input: ChatSessionInput,
  signal: AbortSignal,
): Promise<ChatSessionSnapshot> {
  await cancelCurrentChatRun(input, signal)
  const context = await getContext(input.session.context_id, signal)
  return {
    session: input.session,
    transcript: transcriptFromMessages(context.messages || []),
  }
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
    ...(input.sessionId ? { session_id: input.sessionId } : {}),
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
    if (input.sessionId) {
      const context = await getContext(input.contextId, signal)
      await replaceContext(input.contextId, {
        ...context,
        messages: [],
      }, signal)
    } else {
      await deleteContext(input.contextId, signal)
    }
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

async function cancelCurrentChatRun(
  input: ChatSessionInput,
  signal: AbortSignal,
): Promise<void> {
  const runId = input.currentRunId || input.currentRun?.run_id
  const active = runId && (
    !input.currentRun
    || input.currentRun.run_id !== runId
    || input.currentRun.status === 'running'
    || input.currentRun.status === 'paused'
  )
  if (!active) {
    return
  }
  await cancelAgentRun(runId, { reason: 'chat session changed' }, signal)
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
