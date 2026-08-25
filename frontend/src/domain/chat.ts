import type { ChatResponse, Content } from '../api'

export type ChatSubmission = {
  providerId: string
  modelId: string
  text: string
}

export type ChatTranscriptEntry = {
  entryId: string
  role: string
  text: string
  content: Content
  modelId?: string | null
  finishReason?: string | null
}

export function userEntry(
  submission: ChatSubmission,
  index: number,
): ChatTranscriptEntry {
  return {
    entryId: `user-${index}`,
    role: 'user',
    text: submission.text,
    content: {
      role: 'user',
      content: [{ type: 'text', text: submission.text }],
    },
    modelId: submission.modelId,
  }
}

export function assistantEntry(
  response: ChatResponse,
  index: number,
): ChatTranscriptEntry {
  return {
    entryId: response.response_id || `assistant-${index}`,
    role: response.message.role || 'assistant',
    text: textFromContent(response.message),
    content: response.message,
    modelId: response.model_id,
    finishReason: response.finish_reason,
  }
}

export function transcriptFromMessages(messages: Content[]): ChatTranscriptEntry[] {
  return messages.flatMap((content, index) => {
    const text = visibleTextFromContent(content)
    if (!['user', 'assistant'].includes(content.role) || !text) {
      return []
    }
    return [{
      entryId: messageEntryId(content, index),
      role: content.role,
      text,
      content,
    }]
  })
}

function messageEntryId(content: Content, index: number): string {
  const metadataId = content.metadata?.message_id
  return typeof metadataId === 'string' && metadataId
    ? metadataId
    : `${content.role}-${index + 1}`
}

function textFromContent(message: Content): string {
  return visibleTextFromContent(message) || '[没有文本内容]'
}

function visibleTextFromContent(message: Content): string {
  return (message.content || [])
    .map((part) => part.text)
    .filter((value): value is string => typeof value === 'string')
    .join('\n')
}
