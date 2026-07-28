import { requestJson } from './client'

export type ToolPermission =
  | 'read'
  | 'write'
  | 'process'
  | 'network'
  | 'filesystem'
  | 'shell'
  | 'database'
  | 'external_api'
  | 'destructive'

export type ToolSafetyLevel = 'safe' | 'sensitive' | 'restricted'
export type ToolReplayPolicy = 'safe' | 'idempotent' | 'non_replayable'
export type ToolApprovalStatus = 'requested' | 'approved' | 'denied' | 'expired'

export type ToolDefinition = {
  name: string
  description: string
  parameters_schema?: Record<string, unknown> | null
  permissions?: ToolPermission[]
  safety_level?: ToolSafetyLevel
  requires_approval?: boolean
  replay_policy?: ToolReplayPolicy
  idempotency_key_parameter?: string | null
  metadata?: Record<string, unknown>
}

export type ToolApprovalRequest = {
  approval_id: string
  tool_call_id: string
  tool_name: string
  tool_call?: Record<string, unknown>
  permissions?: ToolPermission[]
  safety_level?: ToolSafetyLevel
  reason?: string | null
  metadata?: Record<string, unknown>
}

export type ToolApprovalDecision = {
  approval_id: string
  tool_call_id: string
  status: ToolApprovalStatus
  reason?: string | null
  metadata?: Record<string, unknown>
}

export type ToolCall = {
  tool_call_id: string
  tool_call: Record<string, unknown>
  approval?: ToolApprovalDecision | null
  metadata?: Record<string, unknown>
}

export type ToolCallResult = {
  tool_call_id: string
  tool_call_result: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export function listTools(): Promise<ToolDefinition[]> {
  return requestJson<ToolDefinition[]>('/tools')
}
