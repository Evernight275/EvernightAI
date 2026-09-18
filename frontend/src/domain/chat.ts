import type { AgentTraceEvent, ChatResponse, Content, ChatSkill } from '../api'

export type ChatSubmission = {
  providerId: string
  modelId: string
  text: string
  skills?: ChatSkill[]
}

export type ChatTranscriptEntry = {
  entryId: string
  role: string
  text: string
  content: Content
  modelId?: string | null
  finishReason?: string | null
  streamRunId?: string
  streaming?: boolean
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

export function applyChatTrace(
  entries: ChatTranscriptEntry[], event: AgentTraceEvent, runId: string,
): ChatTranscriptEntry[] {
  if (event.event_type === 'chat_completed' && event.response) {
    return completeStreamedResponse(entries, event.response, runId)
  }
  if (event.event_type !== 'chat_delta' || !event.text_delta) return entries
  const last = entries.at(-1)
  const continuing = last?.streamRunId === runId && last.streaming
  const text = (continuing ? last.text : '') + event.text_delta
  const entry: ChatTranscriptEntry = {
    entryId: continuing ? last.entryId : `stream-${runId}-${entries.length}`,
    role: 'assistant', text, streamRunId: runId, streaming: true,
    content: { role: 'assistant', content: [{ type: 'text', text }] },
  }
  return continuing ? [...entries.slice(0, -1), entry] : [...entries, entry]
}

export function completeStreamedResponse(
  entries: ChatTranscriptEntry[], response: ChatResponse, runId: string,
): ChatTranscriptEntry[] {
  const last = entries.at(-1)
  const entry = { ...assistantEntry(response, entries.length + 1), streamRunId: runId, streaming: false }
  const replace = last?.streamRunId === runId && (last.streaming
    || (response.response_id && last.entryId === response.response_id)
    || last.text === entry.text)
  if (replace) return [...entries.slice(0, -1), { ...entry, entryId: last.entryId }]
  if (!visibleTextFromContent(response.message)) return entries
  return [...entries, entry]
}
