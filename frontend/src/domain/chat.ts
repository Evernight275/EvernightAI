import type {
  AgentRunState,
  AgentTraceEvent,
  ChatResponse,
  Content,
  ChatSkill,
  ToolCall,
} from '../api'

export type ChatSubmission = {
  providerId: string
  modelId: string
  text: string
  skills?: ChatSkill[]
  workingDirectory?: string
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
  toolActivity?: {
    callId: string
    name: string
    status: 'pending' | 'approval' | 'running' | 'completed' | 'failed'
    argumentsText: string
    resultText?: string
    errorType?: string
    notice?: string
  }
}

export function userEntry(submission: ChatSubmission, index: number): ChatTranscriptEntry {
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

export function assistantEntry(response: ChatResponse, index: number): ChatTranscriptEntry {
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
  let entries: ChatTranscriptEntry[] = []
  for (const [index, content] of messages.entries()) {
    const text = visibleTextFromContent(content)
    if (['user', 'assistant'].includes(content.role) && text) {
      entries.push({ entryId: messageEntryId(content, index), role: content.role, text, content })
    }
    if (content.role === 'assistant') {
      for (const call of content.tool_calls || [])
        entries = upsertTool(
          entries,
          call,
          'history',
          'pending',
          undefined,
          false,
          undefined,
          '结果尚未确认',
        )
    }
    if (content.role === 'tool' && content.tool_call_id) {
      entries = upsertTool(
        entries,
        {
          tool_call_id: content.tool_call_id,
          tool_call: content.name ? { name: content.name } : {},
        },
        'history',
        content.metadata?.error || content.status === 'error' ? 'failed' : 'completed',
        text,
      )
    }
  }
  return entries
}

function messageEntryId(content: Content, index: number): string {
  const metadataId = content.metadata?.message_id
  return typeof metadataId === 'string' && metadataId ? metadataId : `${content.role}-${index + 1}`
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
  entries: ChatTranscriptEntry[],
  event: AgentTraceEvent,
  runId: string,
): ChatTranscriptEntry[] {
  if (event.event_type === 'chat_completed' && event.response) {
    return completeStreamedResponse(entries, event.response, runId)
  }
  const call =
    event.tool_call ||
    (event.approval_request
      ? {
          tool_call_id: event.approval_request.tool_call_id,
          tool_call: event.approval_request.tool_call || { name: event.approval_request.tool_name },
        }
      : undefined)
  if (
    call &&
    [
      'tool_started',
      'tool_completed',
      'tool_failed',
      'tool_approval_requested',
      'tool_approval_decided',
    ].includes(event.event_type)
  ) {
    const status =
      event.event_type === 'tool_started'
        ? 'running'
        : event.event_type === 'tool_completed'
          ? 'completed'
          : event.event_type === 'tool_failed'
            ? 'failed'
            : event.event_type === 'tool_approval_requested'
              ? 'approval'
              : event.approval_decision?.status === 'approved' || event.metadata?.allowed === true
                ? 'pending'
                : 'failed'
    return upsertTool(
      entries,
      call,
      runId,
      status,
      event.error_message ||
        (event.tool_result
          ? JSON.stringify(event.tool_result.tool_call_result, null, 2)
          : status === 'failed'
            ? event.event_type === 'tool_failed'
              ? '工具执行失败'
              : '调用未获批准'
            : undefined),
      false,
      event.error_type || undefined,
    )
  }
  if (event.event_type !== 'chat_delta' || !event.text_delta) return entries
  const last = entries.at(-1)
  const continuing = last?.streamRunId === runId && last.streaming && !last.toolActivity
  const text = (continuing ? last.text : '') + event.text_delta
  const entry: ChatTranscriptEntry = {
    entryId: continuing ? last.entryId : `stream-${runId}-${entries.length}`,
    role: 'assistant',
    text,
    streamRunId: runId,
    streaming: true,
    content: { role: 'assistant', content: [{ type: 'text', text }] },
  }
  return continuing ? [...entries.slice(0, -1), entry] : [...entries, entry]
}

export function completeStreamedResponse(
  entries: ChatTranscriptEntry[],
  response: ChatResponse,
  runId: string,
): ChatTranscriptEntry[] {
  let result = entries
  const last = entries.at(-1)
  const text = visibleTextFromContent(response.message)
  const entry = {
    ...assistantEntry(response, entries.length + 1),
    streamRunId: runId,
    streaming: false,
  }
  const previous = [...entries].reverse().find((item) => !item.toolActivity)
  const alreadyCompleted =
    previous?.streamRunId === runId &&
    !previous.streaming &&
    ((response.response_id && previous.entryId === response.response_id) ||
      (previous.text === text &&
        (last === previous ||
          (!!response.message.tool_calls?.length &&
            response.message.tool_calls.every((call) =>
              entries.some(
                (item) =>
                  item.streamRunId === runId && item.toolActivity?.callId === call.tool_call_id,
              ),
            )))))
  if (last?.streamRunId === runId && last.streaming && !last.toolActivity) {
    result = text
      ? [...entries.slice(0, -1), { ...entry, entryId: last.entryId }]
      : entries.slice(0, -1)
  } else if (text && !alreadyCompleted) {
    result = [...entries, entry]
  }
  for (const call of response.message.tool_calls || [])
    result = upsertTool(result, call, runId, 'pending', undefined, true)
  return result
}

function upsertTool(
  entries: ChatTranscriptEntry[],
  call: ToolCall,
  runId: string,
  status: NonNullable<ChatTranscriptEntry['toolActivity']>['status'],
  resultText?: string,
  preserveStatus = false,
  errorType?: string,
  notice?: string,
): ChatTranscriptEntry[] {
  const turnStart = lastIndex(entries, (entry) => entry.role === 'user')
  const index = lastIndex(
    entries,
    (entry, i) =>
      i > turnStart &&
      entry.toolActivity?.callId === call.tool_call_id &&
      entry.streamRunId === runId,
  )
  const previous = index >= 0 ? entries[index] : undefined
  const previousActivity = previous?.toolActivity
  if (previousActivity && preserveStatus) return entries
  const name = call.tool_call.name || call.tool_call.tool_name
  const args = call.tool_call.arguments ?? call.tool_call.args
  const activity: NonNullable<ChatTranscriptEntry['toolActivity']> = {
    callId: call.tool_call_id,
    name: typeof name === 'string' ? name : previousActivity?.name || '工具调用',
    status,
    errorType,
    notice,
    argumentsText:
      args === undefined ? previousActivity?.argumentsText || '{}' : JSON.stringify(args, null, 2),
    resultText: resultText ?? previousActivity?.resultText,
  }
  const entry: ChatTranscriptEntry = {
    entryId: previous?.entryId || `tool-${runId}-${entries.length}-${call.tool_call_id}`,
    role: 'tool',
    text: '',
    content: { role: 'tool', tool_call_id: call.tool_call_id },
    streamRunId: runId,
    toolActivity: activity,
  }
  return index < 0 ? [...entries, entry] : entries.map((item, i) => (i === index ? entry : item))
}

function lastIndex(
  entries: ChatTranscriptEntry[],
  matches: (entry: ChatTranscriptEntry, index: number) => boolean,
): number {
  for (let index = entries.length - 1; index >= 0; index--) {
    if (matches(entries[index]!, index)) return index
  }
  return -1
}

export const toolStatusLabels = {
  pending: '准备',
  approval: '审批',
  running: '执行中',
  completed: '完成',
  failed: '失败',
}

export function reconcileRunTranscript(
  entries: ChatTranscriptEntry[],
  run: AgentRunState,
): ChatTranscriptEntry[] {
  const events: AgentTraceEvent[] = run.trace?.length
    ? run.trace
    : (run.steps || []).flatMap<AgentTraceEvent>((step) => {
        if (step.step_type === 'chat' && step.response)
          return [{ ...step, event_type: 'chat_completed' as const }]
        if (step.step_type === 'tool') return [{ ...step, event_type: 'tool_completed' as const }]
        if (step.step_type === 'tool_error')
          return [{ ...step, event_type: 'tool_failed' as const }]
        return []
      })
  let result = entries
  if (events.length) {
    result = entries.filter((entry) => entry.streamRunId !== run.run_id)
    const seen = new Set<number>()
    for (const event of events) {
      if (event.sequence != null && seen.has(event.sequence)) continue
      if (event.sequence != null) seen.add(event.sequence)
      result = applyChatTrace(result, event, run.run_id)
    }
  }
  for (const approval of run.pending_approval_requests || []) {
    const recorded = [...result]
      .reverse()
      .find(
        (entry) =>
          entry.streamRunId === run.run_id && entry.toolActivity?.callId === approval.tool_call_id,
      )?.toolActivity
    if (recorded && ['running', 'completed', 'failed'].includes(recorded.status)) continue
    if (
      recorded?.status === 'pending' &&
      events.some(
        (event) =>
          event.event_type === 'tool_approval_decided' &&
          (event.tool_call?.tool_call_id || event.approval_decision?.tool_call_id) ===
            approval.tool_call_id,
      )
    )
      continue
    result = applyChatTrace(
      result,
      { event_type: 'tool_approval_requested', approval_request: approval },
      run.run_id,
    )
  }
  if (run.status && run.status !== 'running') {
    result = result.map((entry) =>
      entry.streamRunId !== run.run_id
        ? entry
        : {
            ...entry,
            streaming: false,
            toolActivity:
              entry.toolActivity &&
              !['completed', 'failed'].includes(entry.toolActivity.status) &&
              !(
                entry.toolActivity.status === 'approval' &&
                run.status === 'paused' &&
                run.pending_approval_requests?.some(
                  (approval) => approval.tool_call_id === entry.toolActivity?.callId,
                )
              )
                ? {
                    ...entry.toolActivity,
                    status: 'pending',
                    notice:
                      run.status === 'paused' ? '运行已暂停，等待继续' : '运行已停止，结果尚未确认',
                  }
                : entry.toolActivity,
          },
    )
  }
  return result
}
