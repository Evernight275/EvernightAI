import type { ToolDefinition, ToolCall } from './tools'

export type MessageRole = 'user' | 'assistant' | 'tool' | 'system'

export type ContentPartType =
  | 'text'
  | 'image'
  | 'video'
  | 'audio'
  | 'file'
  | 'embed'
  | 'link'
  | 'table'
  | 'code'
  | 'function_call'

export type ContentPart = {
  type: ContentPartType | string
  text?: string | null
  url?: string | null
  data?: string | null
  mime_type?: string | null
  detail?: string | null
  metadata?: Record<string, unknown>
}

export type Content = {
  role: MessageRole | string
  content?: ContentPart[] | null
  name?: string | null
  tool_call_id?: string | null
  tool_calls?: ToolCall[] | null
  metadata?: Record<string, unknown>
}

export type ChatSkill = {
  skill_name: string
  render_id?: string | null
  variables?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export type ChatUsage = {
  prompt_tokens?: number | null
  completion_tokens?: number | null
  total_tokens?: number | null
  metadata?: Record<string, unknown>
}

export type ChatRequest = {
  model_id: string
  messages: Content[]
  skills?: ChatSkill[] | null
  tools?: ToolDefinition[] | null
  metadata?: Record<string, unknown>
}

export type ChatResponse = {
  response_id?: string | null
  model_id: string
  message: Content
  finish_reason?: string | null
  usage?: ChatUsage | null
  metadata?: Record<string, unknown>
}
