import { requestJson } from './client'
import type { Content } from './content'

export type SkillCapability = 'chat' | 'tool_use' | 'memory' | 'context' | 'agent' | 'streaming'

export type SkillDefinition = {
  name: string
  description: string
  input_schema?: Record<string, unknown> | null
  output_schema?: Record<string, unknown> | null
  capabilities?: SkillCapability[]
  required_tools?: string[]
  metadata?: Record<string, unknown>
}

export type RenderSkillRequest = {
  render_id?: string | null
  variables?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export type RenderedSkill = {
  render_id: string
  skill_name: string
  messages?: Content[]
  metadata?: Record<string, unknown>
}

export function listSkills(): Promise<SkillDefinition[]> {
  return requestJson<SkillDefinition[]>('/skills')
}

export function getSkill(skillName: string): Promise<SkillDefinition> {
  return requestJson<SkillDefinition>(`/skills/${encodeURIComponent(skillName)}`)
}

export function skillSupports(skillName: string, capability: SkillCapability): Promise<boolean> {
  const params = new URLSearchParams({ capability })
  return requestJson<boolean>(`/skills/${encodeURIComponent(skillName)}/supports?${params}`)
}

export function renderSkill(
  skillName: string,
  request: RenderSkillRequest,
): Promise<RenderedSkill> {
  return requestJson<RenderedSkill>(`/skills/${encodeURIComponent(skillName)}/render`, {
    method: 'POST',
    body: request,
  })
}
