import type { ChatTranscriptEntry } from '../../domain/chat'

export type ChatMessagePresentation = {
  roleLabel: string
  roleClass: string
  markdown: boolean
}

export function chatMessagePresentation(
  entry: ChatTranscriptEntry,
): ChatMessagePresentation {
  const role = entry.role.toLowerCase()
  return {
    roleLabel: role === 'user' ? '你' : role === 'assistant' ? 'EvernightAI' : entry.role,
    roleClass: role === 'user' ? 'user' : 'assistant',
    markdown: role === 'assistant',
  }
}
