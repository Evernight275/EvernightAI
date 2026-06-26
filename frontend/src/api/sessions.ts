import { requestJson } from './client'
import type { ChatResponse, ChatSkill, Content } from './content'
import type { MemoryQuery } from './memory'
import type { ToolApprovalDecision, ToolDefinition } from './tools'
import type { AgentRunState } from './agentRuns'

export type SessionStatus = 'active' | 'archived'

export type Session = {
  session_id: string
  title?: string | null
  context_id: string
  provider_id?: string | null
  model_id?: string | null
  status?: SessionStatus | string
  created_at?: string
  updated_at?: string
  metadata?: Record<string, unknown>
}

export type SessionChatRequest = {
  provider_id?: string | null
  model_id?: string | null
  messages?: Content[]
  retry_from_message_index?: number | null
  memory_query?: MemoryQuery | null
  skills?: ChatSkill[] | null
  tools?: ToolDefinition[] | null
  metadata?: Record<string, unknown>
}

export type SessionAgentRunRequest = SessionChatRequest & {
  max_tool_rounds?: number
  recover_tool_errors?: boolean
  write_memory?: boolean
  tool_approvals?: ToolApprovalDecision[]
  pause_on_approval?: boolean
}

export type SessionChatResult = {
  session: Session
  response: ChatResponse
}

export function createSession(session: Session): Promise<Session> {
  return requestJson<Session>('/sessions', {
    method: 'POST',
    body: session,
  })
}

export function listSessions(): Promise<Session[]> {
  return requestJson<Session[]>('/sessions')
}

export function getSession(sessionId: string): Promise<Session> {
  return requestJson<Session>(`/sessions/${encodeURIComponent(sessionId)}`)
}

export function chatWithSession(
  sessionId: string,
  request: SessionChatRequest,
): Promise<SessionChatResult> {
  return requestJson<SessionChatResult>(`/sessions/${encodeURIComponent(sessionId)}/chat`, {
    method: 'POST',
    body: request,
  })
}

export function startSessionAgentRun(
  sessionId: string,
  request: SessionAgentRunRequest,
): Promise<AgentRunState> {
  return requestJson<AgentRunState>(`/sessions/${encodeURIComponent(sessionId)}/agent-runs`, {
    method: 'POST',
    body: request,
  })
}

export function replaceSession(sessionId: string, session: Session): Promise<Session> {
  return requestJson<Session>(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PUT',
    body: session,
  })
}

export function archiveSession(sessionId: string): Promise<Session> {
  return requestJson<Session>(`/sessions/${encodeURIComponent(sessionId)}/archive`, {
    method: 'POST',
  })
}

export function deleteSession(sessionId: string): Promise<void> {
  return requestJson<void>(`/sessions/${encodeURIComponent(sessionId)}/delete`, {
    method: 'POST',
  })
}
