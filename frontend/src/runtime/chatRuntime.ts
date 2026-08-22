import {
  createContext,
  resumeAgentRun,
  retryAgentRun,
  startAgentRun,
  type AgentRunState,
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
}

export type ChatResumeInput = {
  run: AgentRunState
  status: Extract<ToolApprovalStatus, 'approved' | 'denied'>
}

export function createChatContextId(): string {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `web-chat-${suffix}`
}

export async function prepareChatContext(
  contextId: string,
  signal: AbortSignal,
): Promise<void> {
  await createContext({ context_id: contextId, messages: [] }, signal)
}

export function startChatRun(
  input: ChatRequestInput,
  signal: AbortSignal,
): Promise<AgentRunState> {
  return startAgentRun({
    provider_id: input.submission.providerId,
    context_id: input.contextId,
    model_id: input.submission.modelId,
    messages: [{
      role: 'user',
      content: [{ type: 'text', text: input.submission.text }],
    }],
    tools: input.tools,
    max_tool_rounds: maxToolRounds,
    recover_tool_errors: true,
    write_memory: false,
    pause_on_approval: true,
  }, signal)
}

export function resumeChatRun(
  input: ChatResumeInput,
  signal: AbortSignal,
): Promise<AgentRunState> {
  return resumeAgentRun(input.run.run_id, {
    approvals: approvalDecisions(input.run, input.status),
  }, signal)
}

export function retryChatRun(
  run: AgentRunState,
  signal: AbortSignal,
): Promise<AgentRunState> {
  return retryAgentRun(run.run_id, signal)
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
