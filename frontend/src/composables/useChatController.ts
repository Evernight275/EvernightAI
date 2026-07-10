import {
  computed,
  onMounted,
  onUnmounted,
  ref,
  watch,
  type ComputedRef,
  type Ref,
} from 'vue'
import {
  chatWithContextStream,
  chatWithSession,
  createContext,
  createSession,
  deleteSession,
  getContext,
  approvePendingAgentRun,
  replaceSession,
  resumeAgentRun,
  startAgentRunStream,
  startSessionAgentRun,
  type AgentRunState,
  type AgentTraceEvent,
  type ChatStreamEvent,
  type Content,
  type Context,
  type Session,
  type ToolCall,
  type ToolApprovalRequest,
  type ToolApprovalStatus,
  type ToolCallResult,
  type ToolDefinition,
} from '../api'
import { textPart } from '../format'
import type { ProviderModelChoice } from './useProviderModels'
import { useToast } from './useToast'

const toast = useToast()
const DEFAULT_AGENT_MAX_TOOL_ROUNDS = 8
const CHAT_SETTINGS_STORAGE_KEY = 'evernight.chatSettings.v1'
const DEFAULT_CHAT_SETTINGS = {
  timeoutSeconds: 30,
  streamEnabled: false,
  agentEnabled: true,
}

export type ChatDisplayMessage = Content & {
  outgoing?: boolean
  text: string
  pending?: boolean
  contextIndex?: number
}
type ToolApprovalMessage = ChatDisplayMessage & {
  metadata: {
    kind: 'tool_approval'
    run_id: string
    approval_request: ToolApprovalRequest
    tool_call?: ToolCall | null
  }
}

type UseChatControllerOptions = {
  sessions: Ref<Session[]>
  sortedSessions: ComputedRef<Session[]>
  runs: Ref<AgentRunState[]>
  latestRun: ComputedRef<AgentRunState | undefined>
  tools: Ref<ToolDefinition[]>
  selectedProviderModelChoice: ComputedRef<ProviderModelChoice>
  dashboardError: Ref<string | null>
  refreshDashboard: () => Promise<void>
  syncProviderModelFromSession: (session: Session) => void
}

export function useChatController({
  sessions,
  sortedSessions,
  runs,
  latestRun,
  tools,
  selectedProviderModelChoice,
  dashboardError,
  refreshDashboard,
  syncProviderModelFromSession,
}: UseChatControllerOptions) {
  const storedChatSettings = readChatSettings()
  const selectedSessionId = ref<string | null>(null)
  const selectedContext = ref<Context | null>(null)
  const contextLoading = ref(false)
  const chatDraft = ref('')
  const pendingChatMessages = ref<ChatDisplayMessage[]>([])
  const pendingChatSessionId = ref<string | null>(null)
  const pendingAssistantHasDelta = ref(false)
  const chatTimeoutSeconds = ref(storedChatSettings.timeoutSeconds)
  const chatStreamEnabled = ref(storedChatSettings.streamEnabled)
  const chatAgentEnabled = ref(storedChatSettings.agentEnabled)
  let syncingStoredChatSettings = false
  const sendingMessage = ref(false)
  const approvingToolApproval = ref(false)
  const creatingSession = ref(false)
  const chatError = ref<string | null>(null)
  const activeAgentRunId = ref<string | null>(null)
  const currentAgentRunPaused = ref(false)

  watch(
    [chatTimeoutSeconds, chatStreamEnabled, chatAgentEnabled],
    ([timeoutSeconds, streamEnabled, agentEnabled]) => {
      if (syncingStoredChatSettings) {
        return
      }

      writeChatSettings({
        timeoutSeconds: normalizeTimeoutSeconds(timeoutSeconds),
        streamEnabled,
        agentEnabled,
      })
    },
    { flush: 'sync' },
  )

  function syncStoredChatSettings(event: StorageEvent) {
    if (event.key !== null && event.key !== CHAT_SETTINGS_STORAGE_KEY) {
      return
    }

    const nextSettings = readChatSettings()
    syncingStoredChatSettings = true
    try {
      chatTimeoutSeconds.value = nextSettings.timeoutSeconds
      chatStreamEnabled.value = nextSettings.streamEnabled
      chatAgentEnabled.value = nextSettings.agentEnabled
    } finally {
      syncingStoredChatSettings = false
    }
  }

  onMounted(() => {
    window.addEventListener('storage', syncStoredChatSettings)
  })

  onUnmounted(() => {
    window.removeEventListener('storage', syncStoredChatSettings)
  })

  const selectedSession = computed(() => (
    sessions.value.find((session) => session.session_id === selectedSessionId.value) || null
  ))

  const chatDisplayError = computed(() => chatError.value || dashboardError.value)

  const chatMessages = computed<ChatDisplayMessage[]>(() => {
    const pendingMessages = pendingChatSessionId.value === selectedSessionId.value
      ? pendingChatMessages.value
      : []
    const approvalMessages = selectedSession.value
      ? approvalMessagesForSession(selectedSession.value, pendingMessages)
      : []

    if (selectedContext.value?.messages?.length) {
      return [
        ...selectedContext.value.messages
          .map((message, contextIndex) => ({
            ...message,
            text: textPart(message),
            outgoing: message.role === 'assistant',
            contextIndex,
          }))
          .filter((message) => isActiveMessage(message)),
        ...approvalMessages,
        ...pendingMessages,
      ]
    }

    const messages: ChatDisplayMessage[] = [
      ...approvalMessages,
      ...pendingMessages,
    ]

    if (messages.length > 0) {
      return messages
    }

    if (selectedSession.value) {
      messages.push({
        role: 'system',
        text: `${selectedSession.value.title || selectedSession.value.session_id} 暂无上下文消息。`,
      })
      return messages
    }

    const run = latestRun.value
    if (run?.response?.message) {
      messages.push({
        ...run.response.message,
        role: run.response.message.role || 'assistant',
        text: textPart(run.response.message),
        outgoing: true,
      })
    }

    if (messages.length === 0) {
      messages.push({
        role: 'system',
        text: '请选择一个会话开始查看上下文。',
      })
    }

    return messages
  })

  async function selectSession(session: Session) {
    selectedSessionId.value = session.session_id
    syncProviderModelFromSession(session)
    await loadSelectedContext()
  }

  async function loadSelectedContext() {
    if (!selectedSession.value) {
      selectedContext.value = null
      return
    }

    contextLoading.value = true
    chatError.value = null

    try {
      selectedContext.value = await getContext(selectedSession.value.context_id)
    } catch (error) {
      selectedContext.value = null
      chatError.value = error instanceof Error ? error.message : '上下文加载失败'
    } finally {
      contextLoading.value = false
    }
  }

  async function sendChatMessage(text: string) {
    await sendChatMessageInternal({
      text,
      retryFromMessageIndex: null,
    })
  }

  async function retryChatMessage(message: ChatDisplayMessage) {
    if (message.contextIndex === undefined) {
      return
    }

    await sendChatMessageInternal({
      text: '',
      retryFromMessageIndex: message.contextIndex,
    })
  }

  async function sendChatMessageInternal(options: {
    text: string
    retryFromMessageIndex: number | null
  }) {
    const session = selectedSession.value || await createChatSession('新会话')
    const messageText = options.text.trim()
    const retryFromMessageIndex = options.retryFromMessageIndex
    const isRetry = retryFromMessageIndex !== null

    if (!session || (!isRetry && messageText === '')) {
      return
    }

    sendingMessage.value = true
    chatError.value = null
    const routeLabel = chatAgentEnabled.value ? 'Agent' : '模型'
    const assistantRunningText = chatStreamEnabled.value
      ? `${routeLabel} 正在流式响应...`
      : `${routeLabel} 正在运行...`
    pendingChatSessionId.value = session.session_id
    pendingAssistantHasDelta.value = false
    pendingChatMessages.value = [
      ...(
        isRetry
          ? []
          : [{
              role: 'user',
              content: [{ type: 'text', text: messageText }],
              text: messageText,
            } satisfies ChatDisplayMessage]
      ),
      {
        role: 'assistant',
        content: [{ type: 'text', text: assistantRunningText }],
        text: assistantRunningText,
        pending: true,
      },
    ]
    chatDraft.value = ''

    try {
      const request = {
        provider_id: selectedProviderModelChoice.value.providerId,
        model_id: selectedProviderModelChoice.value.modelId,
        messages: isRetry
          ? []
          : [
              {
                role: 'user',
                content: [{ type: 'text', text: messageText }],
              },
            ],
        retry_from_message_index: retryFromMessageIndex,
        tools: tools.value,
        metadata: {
          source: 'frontend-chat',
          timeout_seconds: chatTimeoutSeconds.value,
          stream: chatStreamEnabled.value,
        },
      }

      if (chatStreamEnabled.value && chatAgentEnabled.value) {
        const runId = newId('run')
        activeAgentRunId.value = runId
        currentAgentRunPaused.value = false
        await startAgentRunStream({
          ...request,
          context_id: session.context_id,
          metadata: {
            ...request.metadata,
            session_id: session.session_id,
            run_id: runId,
          },
          max_tool_rounds: DEFAULT_AGENT_MAX_TOOL_ROUNDS,
          recover_tool_errors: true,
          write_memory: false,
          pause_on_approval: true,
        }, handleAgentStreamEvent)
      } else if (chatStreamEnabled.value) {
        setPendingAssistantText('', true)
        await chatWithContextStream({
          ...request,
          context_id: session.context_id,
          metadata: {
            ...request.metadata,
            session_id: session.session_id,
          },
        }, handleChatStreamEvent)
      } else if (chatAgentEnabled.value) {
        const state = await startSessionAgentRun(session.session_id, {
          ...request,
          max_tool_rounds: DEFAULT_AGENT_MAX_TOOL_ROUNDS,
          recover_tool_errors: true,
          write_memory: false,
          pause_on_approval: true,
        })
        if (state.status === 'paused' && state.pending_approval_requests?.length) {
          currentAgentRunPaused.value = true
          for (const approval of state.pending_approval_requests) {
            appendPendingApproval(state.run_id, approval, state.pending_tool_calls?.[0] || null)
          }
          setPendingAssistantText('等待工具审批...', true)
        }
      } else {
        await chatWithSession(session.session_id, request)
      }
      await refreshDashboard()
      if (!currentAgentRunPaused.value) {
        clearPendingMessages()
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Agent 运行失败'
      chatError.value = message
      pendingChatMessages.value = [
        ...pendingChatMessages.value.filter((pending) => pending.role === 'user'),
        {
          role: 'system',
          content: [{ type: 'text', text: `Agent 运行失败：${message}` }],
          text: `Agent 运行失败：${message}`,
        },
      ]
      pendingAssistantHasDelta.value = false
    } finally {
      sendingMessage.value = false
      if (!currentAgentRunPaused.value) {
        activeAgentRunId.value = null
      }
    }
  }

  async function decideToolApproval(message: ChatDisplayMessage, status: ToolApprovalStatus) {
    const approvalMessage = asToolApprovalMessage(message)
    if (approvalMessage === null) {
      return
    }

    approvingToolApproval.value = true
    chatError.value = null
    try {
      const approval = approvalMessage.metadata.approval_request
      if (status === 'approved') {
        await approvePendingAgentRun(approvalMessage.metadata.run_id)
      } else {
        await resumeAgentRun(approvalMessage.metadata.run_id, {
          approvals: [
            {
              approval_id: approval.approval_id,
              tool_call_id: approval.tool_call_id,
              status,
            },
          ],
        })
      }
      currentAgentRunPaused.value = false
      activeAgentRunId.value = null
      removePendingApproval(approval.approval_id)
      await refreshDashboard()
      await loadSelectedContext()
      clearPendingMessages()
    } catch (error) {
      chatError.value = error instanceof Error ? error.message : '工具审批失败'
    } finally {
      approvingToolApproval.value = false
    }
  }

  async function createNewChatSession() {
    creatingSession.value = true
    chatError.value = null

    try {
      await createChatSession('新会话')
      clearPendingMessages()
      chatDraft.value = ''
      await refreshDashboard()
      toast.success('会话创建成功')
    } catch (error) {
      chatError.value = error instanceof Error ? error.message : '新建会话失败'
      toast.error(chatError.value)
    } finally {
      creatingSession.value = false
    }
  }

  async function createChatSession(title: string): Promise<Session> {
    const contextId = newId('ctx')
    const sessionId = newId('session')
    const providerId = selectedProviderModelChoice.value.providerId
    const modelId = selectedProviderModelChoice.value.modelId

    await createContext({
      context_id: contextId,
      messages: [],
    })
    const session = await createSession({
      session_id: sessionId,
      title,
      context_id: contextId,
      provider_id: providerId,
      model_id: modelId,
    })
    selectedSessionId.value = sessionId
    selectedContext.value = {
      context_id: contextId,
      messages: [],
    }

    return session
  }

  async function renameSession(session: Session) {
    const nextTitle = window.prompt('输入新的会话名称', session.title || '')
    if (nextTitle === null) {
      return
    }

    const cleanTitle = nextTitle.trim()
    if (cleanTitle === '' || cleanTitle === session.title) {
      return
    }

    chatError.value = null

    try {
      await replaceSession(session.session_id, {
        ...session,
        title: cleanTitle,
      })
      await refreshDashboard()
      toast.success('会话重命名成功')
    } catch (error) {
      chatError.value = error instanceof Error ? error.message : '重命名会话失败'
      toast.error(chatError.value)
    }
  }

  async function removeSession(session: Session) {
    const confirmed = window.confirm(`删除会话「${session.title || session.session_id}」？`)
    if (!confirmed) {
      return
    }

    chatError.value = null

    try {
      await deleteSession(session.session_id)
      if (selectedSessionId.value === session.session_id) {
        selectedSessionId.value = null
        selectedContext.value = null
        clearPendingMessages()
      }
      await refreshDashboard()
      toast.success('会话删除成功')
    } catch (error) {
      chatError.value = error instanceof Error ? error.message : '删除会话失败'
      toast.error(chatError.value)
    }
  }

  function ensureSelectedSession() {
    if (
      selectedSessionId.value !== null
      && sessions.value.some((session) => session.session_id === selectedSessionId.value)
    ) {
      return
    }

    selectedSessionId.value = sortedSessions.value[0]?.session_id || null
    if (selectedSession.value) {
      syncProviderModelFromSession(selectedSession.value)
    }
  }

  function handleChatStreamEvent(event: ChatStreamEvent) {
    if (event.event_type === 'message_delta') {
      const text = event.text_delta || event.content_part?.text || ''
      appendPendingAssistantText(text)
      return
    }

    if (event.event_type === 'error') {
      throw new Error(event.error_message || event.error_type || '流式响应失败')
    }
  }

  function handleAgentStreamEvent(event: AgentTraceEvent) {
    if (event.event_type === 'run_started') {
      setPendingAssistantText(event.summary || 'Agent 已开始运行...', true)
      pendingAssistantHasDelta.value = false
      return
    }

    if (event.event_type === 'chat_delta') {
      appendPendingAssistantText(event.text_delta || '')
      return
    }

    if (event.event_type === 'chat_completed') {
      const text = event.message ? textPart(event.message) : ''
      if (text) {
        setPendingAssistantText(text, true)
        pendingAssistantHasDelta.value = true
      }
      const toolCalls = event.message?.tool_calls || event.response?.message.tool_calls || []
      if (toolCalls.length > 0) {
        appendPendingToolCalls(toolCalls)
        setPendingAssistantText('正在调用工具...', true)
        pendingAssistantHasDelta.value = false
      }
      return
    }

    if (event.event_type === 'tool_approval_requested' && event.tool_call) {
      appendPendingToolCalls([event.tool_call])
      if (event.approval_request && activeAgentRunId.value) {
        appendPendingApproval(activeAgentRunId.value, event.approval_request, event.tool_call)
      }
      setPendingAssistantText(event.summary || '等待工具审批...', true)
      pendingAssistantHasDelta.value = false
      return
    }

    if (event.event_type === 'tool_completed') {
      appendPendingToolResult(event)
      if (event.tool_call) {
        markPendingToolCallDone(event.tool_call.tool_call_id)
      }
      setPendingAssistantText('工具已返回，继续生成...', true)
      pendingAssistantHasDelta.value = false
      return
    }

    if (event.event_type === 'tool_failed') {
      appendPendingToolResult(event)
      if (event.tool_call) {
        markPendingToolCallDone(event.tool_call.tool_call_id)
      }
      setPendingAssistantText(event.summary || event.error_message || '工具调用失败', false)
      pendingAssistantHasDelta.value = false
      return
    }

    if (event.event_type === 'run_stopped') {
      markPendingAssistantDone()
      currentAgentRunPaused.value = false
      return
    }

    if (event.event_type === 'run_paused') {
      currentAgentRunPaused.value = true
      if (event.approval_request && activeAgentRunId.value) {
        appendPendingApproval(activeAgentRunId.value, event.approval_request, event.tool_call || null)
      }
      setPendingAssistantText(event.summary || '等待工具审批...', true)
    }
  }

  function appendPendingApproval(
    runId: string,
    approval: ToolApprovalRequest,
    toolCall: ToolCall | null,
  ) {
    const alreadyExists = pendingChatMessages.value.some((message) => (
      message.metadata?.kind === 'tool_approval'
      && message.metadata?.approval_request
      && isApprovalRequest(message.metadata.approval_request)
      && message.metadata.approval_request.approval_id === approval.approval_id
    ))
    if (alreadyExists) {
      return
    }

    const permissionLabel = approval.permissions?.join(', ') || '无特殊权限'
    pendingChatMessages.value = [
      ...pendingChatMessages.value,
      makeApprovalMessage(runId, approval, toolCall, permissionLabel),
    ]
  }

  function appendPendingToolCalls(toolCalls: ToolCall[]) {
    const existingIds = new Set(
      pendingChatMessages.value
        .flatMap((message) => message.tool_calls || [])
        .map((call) => call.tool_call_id),
    )
    const nextMessages = toolCalls
      .filter((call) => !existingIds.has(call.tool_call_id))
      .map((call) => ({
        role: 'system',
        content: [{ type: 'text', text: toolCallText(call) }],
        text: toolCallText(call),
        tool_calls: [call],
        pending: true,
      }) satisfies ChatDisplayMessage)

    if (nextMessages.length === 0) {
      return
    }

    pendingChatMessages.value = [
      ...pendingChatMessages.value,
      ...nextMessages,
    ]
  }

  function appendPendingToolResult(event: AgentTraceEvent) {
    const toolMessage = event.message
      ? {
          ...event.message,
          text: textPart(event.message) || toolResultText(event.tool_result),
        }
      : toolResultMessage(event.tool_result, event.error_message)

    if (toolMessage === null) {
      return
    }

    const resultId = toolMessage.tool_call_id
    const alreadyHasResult = pendingChatMessages.value.some((message) => (
      message.role === 'tool' && message.tool_call_id === resultId
    ))
    if (alreadyHasResult) {
      return
    }

    pendingChatMessages.value = [
      ...pendingChatMessages.value,
      toolMessage,
    ]
  }

  function markPendingToolCallDone(toolCallId: string) {
    pendingChatMessages.value = pendingChatMessages.value.map((message) => {
      const hasToolCall = (message.tool_calls || []).some((call) => (
        call.tool_call_id === toolCallId
      ))
      if (!hasToolCall) {
        return message
      }

      return {
        ...message,
        pending: false,
      }
    })
  }

  function appendPendingAssistantText(text: string) {
    if (!text) {
      return
    }

    const assistant = pendingChatMessages.value.find((message) => message.role === 'assistant')
    const current = assistant?.pending
      && pendingAssistantHasDelta.value
      ? assistant.text
      : ''
    pendingAssistantHasDelta.value = true
    setPendingAssistantText(current + text, true)
  }

  function setPendingAssistantText(text: string, pending: boolean) {
    const messages = pendingChatMessages.value.filter((message) => message.role !== 'assistant')
    if (messages.length === pendingChatMessages.value.length && pendingChatMessages.value.length > 0) {
      return
    }

    pendingChatMessages.value = [
      ...messages,
      {
        role: 'assistant',
        content: [{ type: 'text', text }],
        text,
        pending,
      },
    ]
  }

  function markPendingAssistantDone() {
    const assistant = pendingChatMessages.value.find((message) => message.role === 'assistant')
    if (!assistant) {
      return
    }

    setPendingAssistantText(assistant.text, false)
  }

  function clearPendingMessages() {
    pendingChatMessages.value = []
    pendingChatSessionId.value = null
    pendingAssistantHasDelta.value = false
    currentAgentRunPaused.value = false
  }

  function removePendingApproval(approvalId: string) {
    pendingChatMessages.value = pendingChatMessages.value.filter((message) => {
      const approval = message.metadata?.approval_request
      return !(isApprovalRequest(approval) && approval.approval_id === approvalId)
    })
  }

  function approvalMessagesForSession(
    session: Session,
    pendingMessages: ChatDisplayMessage[],
  ): ChatDisplayMessage[] {
    const pendingApprovalIds = new Set(
      pendingMessages
        .map((message) => message.metadata?.approval_request)
        .filter(isApprovalRequest)
        .map((approval) => approval.approval_id),
    )

    return runs.value
      .filter((run) => run.status === 'paused')
      .filter((run) => runMatchesSession(run, session))
      .flatMap((run) => (
        (run.pending_approval_requests || [])
          .filter((approval) => !pendingApprovalIds.has(approval.approval_id))
          .map((approval) => makeApprovalMessage(
            run.run_id,
            approval,
            (run.pending_tool_calls || []).find((call) => call.tool_call_id === approval.tool_call_id) || null,
          ))
      ))
  }

  return {
    selectedSessionId,
    selectedContext,
    selectedSession,
    contextLoading,
    chatDraft,
    chatTimeoutSeconds,
    chatStreamEnabled,
    chatAgentEnabled,
    sendingMessage,
    approvingToolApproval,
    creatingSession,
    chatDisplayError,
    chatMessages,
    selectSession,
    loadSelectedContext,
    sendChatMessage,
    decideToolApproval,
    retryChatMessage,
    createNewChatSession,
    renameSession,
    removeSession,
    ensureSelectedSession,
  }
}

function readChatSettings(): typeof DEFAULT_CHAT_SETTINGS {
  try {
    const storedValue = localStorage.getItem(CHAT_SETTINGS_STORAGE_KEY)
    if (!storedValue) {
      return { ...DEFAULT_CHAT_SETTINGS }
    }

    const parsedValue = JSON.parse(storedValue) as Partial<typeof DEFAULT_CHAT_SETTINGS>
    return {
      timeoutSeconds: normalizeTimeoutSeconds(parsedValue.timeoutSeconds),
      streamEnabled: typeof parsedValue.streamEnabled === 'boolean'
        ? parsedValue.streamEnabled
        : DEFAULT_CHAT_SETTINGS.streamEnabled,
      agentEnabled: typeof parsedValue.agentEnabled === 'boolean'
        ? parsedValue.agentEnabled
        : DEFAULT_CHAT_SETTINGS.agentEnabled,
    }
  } catch {
    return { ...DEFAULT_CHAT_SETTINGS }
  }
}

function writeChatSettings(settings: typeof DEFAULT_CHAT_SETTINGS) {
  try {
    localStorage.setItem(CHAT_SETTINGS_STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // Storage can be unavailable in restricted browser contexts.
  }
}

function normalizeTimeoutSeconds(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 1 && value <= 600
    ? Math.round(value)
    : DEFAULT_CHAT_SETTINGS.timeoutSeconds
}

function runMatchesSession(run: AgentRunState, session: Session): boolean {
  return (
    run.request.context_id === session.context_id
    || run.request.metadata?.session_id === session.session_id
  )
}

function makeApprovalMessage(
  runId: string,
  approval: ToolApprovalRequest,
  toolCall: ToolCall | null,
  permissionLabel = approval.permissions?.join(', ') || '无特殊权限',
): ToolApprovalMessage {
  return {
    role: 'system',
    content: [{ type: 'text', text: `等待审批：${approval.tool_name}` }],
    text: `等待审批：${approval.tool_name} · ${approval.safety_level || 'safe'} · ${permissionLabel}`,
    pending: true,
    metadata: {
      kind: 'tool_approval',
      run_id: runId,
      approval_request: approval,
      tool_call: toolCall,
    },
  }
}

function isActiveMessage(message: Content): boolean {
  return message.status === undefined || message.status === null || message.status === 'active'
}

function asToolApprovalMessage(message: ChatDisplayMessage): ToolApprovalMessage | null {
  const metadata = message.metadata
  if (
    metadata?.kind !== 'tool_approval'
    || typeof metadata.run_id !== 'string'
    || !isApprovalRequest(metadata.approval_request)
  ) {
    return null
  }

  return message as ToolApprovalMessage
}

function isApprovalRequest(value: unknown): value is ToolApprovalRequest {
  return (
    typeof value === 'object'
    && value !== null
    && typeof (value as ToolApprovalRequest).approval_id === 'string'
    && typeof (value as ToolApprovalRequest).tool_call_id === 'string'
    && typeof (value as ToolApprovalRequest).tool_name === 'string'
  )
}

function toolCallText(call: ToolCall): string {
  return formatJson({
    tool_call_id: call.tool_call_id,
    tool_call: call.tool_call,
  })
}

function toolResultText(result: ToolCallResult | null | undefined): string {
  if (!result) {
    return ''
  }

  return formatJson(result)
}

function toolResultMessage(
  result: ToolCallResult | null | undefined,
  errorMessage: string | null | undefined,
): ChatDisplayMessage | null {
  if (result) {
    const text = toolResultText(result)
    return {
      role: 'tool',
      tool_call_id: result.tool_call_id,
      content: [{ type: 'text', text }],
      text,
    }
  }

  if (!errorMessage) {
    return null
  }

  return {
    role: 'tool',
    content: [{ type: 'text', text: errorMessage }],
    text: errorMessage,
    status: 'error',
  }
}

function formatJson(value: unknown): string {
  if (typeof value === 'string') {
    return value
  }

  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function newId(prefix: string): string {
  if (crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID()}`
  }

  return `${prefix}-${Date.now()}`
}
