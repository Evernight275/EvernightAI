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
  type ContentPart,
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

type ChatMessageInput = {
  text: string
  images: ContentPart[]
}

type PendingChatState = {
  messages: ChatDisplayMessage[]
  assistantHasDelta: boolean
  activeAgentRunId: string | null
  runPaused: boolean
  sending: boolean
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
  const pendingChatStates = ref<Record<string, PendingChatState>>({})
  const hiddenApprovalIds = ref<Set<string>>(new Set())
  const chatTimeoutSeconds = ref(storedChatSettings.timeoutSeconds)
  const chatStreamEnabled = ref(storedChatSettings.streamEnabled)
  const chatAgentEnabled = ref(storedChatSettings.agentEnabled)
  let syncingStoredChatSettings = false
  const approvingToolApproval = ref(false)
  const creatingSession = ref(false)
  const chatError = ref<string | null>(null)

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

  const sendingMessage = computed(() => (
    selectedSessionId.value !== null
    && pendingChatStates.value[selectedSessionId.value]?.sending === true
  ))

  const chatDisplayError = computed(() => chatError.value || dashboardError.value)

  const chatMessages = computed<ChatDisplayMessage[]>(() => {
    const pendingMessages = selectedSessionId.value
      ? pendingChatStates.value[selectedSessionId.value]?.messages || []
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
    const session = selectedSession.value
    if (!session) {
      selectedContext.value = null
      return
    }

    contextLoading.value = true
    chatError.value = null

    try {
      const context = await getContext(session.context_id)
      if (selectedSessionId.value === session.session_id) {
        selectedContext.value = context
      }
    } catch (error) {
      if (selectedSessionId.value === session.session_id) {
        selectedContext.value = null
        chatError.value = error instanceof Error ? error.message : '上下文加载失败'
      }
    } finally {
      if (selectedSessionId.value === session.session_id) {
        contextLoading.value = false
      }
    }
  }

  async function sendChatMessage(input: ChatMessageInput) {
    await sendChatMessageInternal({
      text: input.text,
      images: input.images,
      retryFromMessageIndex: null,
    })
  }

  async function retryChatMessage(message: ChatDisplayMessage) {
    if (message.contextIndex === undefined) {
      return
    }

    await sendChatMessageInternal({
      text: '',
      images: [],
      retryFromMessageIndex: message.contextIndex,
    })
  }

  async function sendChatMessageInternal(options: {
    text: string
    images: ContentPart[]
    retryFromMessageIndex: number | null
  }) {
    const session = selectedSession.value || await createChatSession('新会话')
    const messageText = options.text.trim()
    const retryFromMessageIndex = options.retryFromMessageIndex
    const isRetry = retryFromMessageIndex !== null
    const messageParts: ContentPart[] = [
      ...(messageText ? [{ type: 'text' as const, text: messageText }] : []),
      ...options.images,
    ]

    if (!session || (!isRetry && messageParts.length === 0)) {
      return
    }

    if (isSessionSending(session.session_id)) {
      return
    }

    const sessionId = session.session_id
    const streamEnabled = chatStreamEnabled.value
    const agentEnabled = chatAgentEnabled.value
    const timeoutSeconds = chatTimeoutSeconds.value
    chatError.value = null
    const routeLabel = agentEnabled ? 'Agent' : '模型'
    const assistantRunningText = streamEnabled
      ? `${routeLabel} 正在流式响应...`
      : `${routeLabel} 正在运行...`
    setPendingState(sessionId, {
      messages: [
        ...(
          isRetry
            ? []
            : [{
                role: 'user',
                content: messageParts,
                text: messageText || `发送了 ${options.images.length} 张图片`,
              } satisfies ChatDisplayMessage]
        ),
        {
          role: 'assistant',
          content: [{ type: 'text', text: assistantRunningText }],
          text: assistantRunningText,
          pending: true,
        },
      ],
      assistantHasDelta: false,
      activeAgentRunId: null,
      runPaused: false,
      sending: true,
    })
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
                content: messageParts,
              },
            ],
        retry_from_message_index: retryFromMessageIndex,
        tools: tools.value,
        metadata: {
          source: 'frontend-chat',
          timeout_seconds: timeoutSeconds,
          stream: streamEnabled,
        },
      }

      if (streamEnabled && agentEnabled) {
        const runId = newId('run')
        updatePendingState(sessionId, (state) => ({
          ...state,
          activeAgentRunId: runId,
          runPaused: false,
        }))
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
        }, (event) => handleAgentStreamEvent(sessionId, event))
      } else if (streamEnabled) {
        setPendingAssistantText(sessionId, '', true)
        await chatWithContextStream({
          ...request,
          context_id: session.context_id,
          metadata: {
            ...request.metadata,
            session_id: session.session_id,
          },
        }, (event) => handleChatStreamEvent(sessionId, event))
      } else if (agentEnabled) {
        const state = await startSessionAgentRun(session.session_id, {
          ...request,
          max_tool_rounds: DEFAULT_AGENT_MAX_TOOL_ROUNDS,
          recover_tool_errors: true,
          write_memory: false,
          pause_on_approval: true,
        })
        if (state.status === 'paused' && state.pending_approval_requests?.length) {
          updatePendingState(sessionId, (pending) => ({
            ...pending,
            runPaused: true,
          }))
          for (const approval of state.pending_approval_requests) {
            appendPendingApproval(sessionId, state.run_id, approval, state.pending_tool_calls?.[0] || null)
          }
          setPendingAssistantText(sessionId, '等待工具审批...', true)
        }
      } else {
        await chatWithSession(session.session_id, request)
      }
      await refreshDashboard()
      if (!pendingState(sessionId)?.runPaused) {
        clearPendingMessages(sessionId)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Agent 运行失败'
      chatError.value = message
      updatePendingState(sessionId, (state) => ({
        ...state,
        messages: [
          ...state.messages.filter((pending) => pending.role === 'user'),
          {
            role: 'system',
            content: [{ type: 'text', text: `Agent 运行失败：${message}` }],
            text: `Agent 运行失败：${message}`,
          },
        ],
        assistantHasDelta: false,
        runPaused: false,
      }))
    } finally {
      updatePendingState(sessionId, (state) => ({
        ...state,
        activeAgentRunId: state.runPaused ? state.activeAgentRunId : null,
        sending: false,
      }))
    }
  }

  async function decideToolApproval(message: ChatDisplayMessage, status: ToolApprovalStatus) {
    const approvalMessage = asToolApprovalMessage(message)
    if (approvalMessage === null) {
      return
    }

    const sessionId = selectedSessionId.value
    if (sessionId === null) {
      return
    }

    approvingToolApproval.value = true
    chatError.value = null
    const approval = approvalMessage.metadata.approval_request
    const pendingSnapshot = [...(pendingState(sessionId)?.messages || [])]
    const assistantDeltaSnapshot = pendingState(sessionId)?.assistantHasDelta || false
    hideApproval(approval.approval_id)
    clearPendingApprovalArtifacts(sessionId, approval.tool_call_id)
    try {
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
      updatePendingState(sessionId, (state) => ({
        ...state,
        activeAgentRunId: null,
        runPaused: false,
      }))
      removePendingApproval(approval.approval_id)
      await refreshDashboard()
      await loadSelectedContext()
      clearPendingMessages(sessionId)
    } catch (error) {
      updatePendingState(sessionId, (state) => ({
        ...state,
        messages: pendingSnapshot,
        assistantHasDelta: assistantDeltaSnapshot,
      }))
      showApproval(approval.approval_id)
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
        clearPendingMessages(session.session_id)
        selectedSessionId.value = null
        selectedContext.value = null
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

  function handleChatStreamEvent(sessionId: string, event: ChatStreamEvent) {
    if (event.event_type === 'message_delta') {
      const text = event.text_delta || event.content_part?.text || ''
      appendPendingAssistantText(sessionId, text)
      return
    }

    if (event.event_type === 'error') {
      throw new Error(event.error_message || event.error_type || '流式响应失败')
    }
  }

  function handleAgentStreamEvent(sessionId: string, event: AgentTraceEvent) {
    if (event.event_type === 'run_started') {
      setPendingAssistantText(sessionId, event.summary || 'Agent 已开始运行...', true)
      setPendingAssistantHasDelta(sessionId, false)
      return
    }

    if (event.event_type === 'chat_delta') {
      appendPendingAssistantText(sessionId, event.text_delta || '')
      return
    }

    if (event.event_type === 'chat_completed') {
      const text = event.message ? textPart(event.message) : ''
      if (text) {
        setPendingAssistantText(sessionId, text, true)
        setPendingAssistantHasDelta(sessionId, true)
      }
      const toolCalls = event.message?.tool_calls || event.response?.message?.tool_calls || []
      if (toolCalls.length > 0) {
        appendPendingToolCalls(sessionId, toolCalls)
        setPendingAssistantText(sessionId, '正在调用工具...', true)
        setPendingAssistantHasDelta(sessionId, false)
      }
      return
    }

    if (event.event_type === 'tool_approval_requested' && event.tool_call) {
      appendPendingToolCalls(sessionId, [event.tool_call])
      const runId = pendingState(sessionId)?.activeAgentRunId
      if (event.approval_request && runId) {
        appendPendingApproval(sessionId, runId, event.approval_request, event.tool_call)
      }
      setPendingAssistantText(sessionId, event.summary || '等待工具审批...', true)
      setPendingAssistantHasDelta(sessionId, false)
      return
    }

    if (event.event_type === 'tool_completed') {
      appendPendingToolResult(sessionId, event)
      if (event.tool_call) {
        markPendingToolCallDone(sessionId, event.tool_call.tool_call_id)
      }
      setPendingAssistantText(sessionId, '工具已返回，继续生成...', true)
      setPendingAssistantHasDelta(sessionId, false)
      return
    }

    if (event.event_type === 'tool_failed') {
      appendPendingToolResult(sessionId, event)
      if (event.tool_call) {
        markPendingToolCallDone(sessionId, event.tool_call.tool_call_id)
      }
      setPendingAssistantText(sessionId, event.summary || event.error_message || '工具调用失败', false)
      setPendingAssistantHasDelta(sessionId, false)
      return
    }

    if (event.event_type === 'run_stopped') {
      markPendingAssistantDone(sessionId)
      updatePendingState(sessionId, (state) => ({
        ...state,
        runPaused: false,
      }))
      return
    }

    if (event.event_type === 'run_paused') {
      updatePendingState(sessionId, (state) => ({
        ...state,
        runPaused: true,
      }))
      const runId = pendingState(sessionId)?.activeAgentRunId
      if (event.approval_request && runId) {
        appendPendingApproval(sessionId, runId, event.approval_request, event.tool_call || null)
      }
      setPendingAssistantText(sessionId, event.summary || '等待工具审批...', true)
    }
  }

  function appendPendingApproval(
    sessionId: string,
    runId: string,
    approval: ToolApprovalRequest,
    toolCall: ToolCall | null,
  ) {
    const state = pendingState(sessionId)
    if (!state) {
      return
    }

    const alreadyExists = state.messages.some((message) => (
      message.metadata?.kind === 'tool_approval'
      && message.metadata?.approval_request
      && isApprovalRequest(message.metadata.approval_request)
      && message.metadata.approval_request.approval_id === approval.approval_id
    ))
    if (alreadyExists) {
      return
    }

    const permissionLabel = approval.permissions?.join(', ') || '无特殊权限'
    updatePendingState(sessionId, (pending) => ({
      ...pending,
      messages: [
        ...pending.messages,
        makeApprovalMessage(runId, approval, toolCall, permissionLabel),
      ],
    }))
  }

  function appendPendingToolCalls(sessionId: string, toolCalls: ToolCall[]) {
    const state = pendingState(sessionId)
    if (!state) {
      return
    }

    const existingIds = new Set(
      state.messages
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

    updatePendingState(sessionId, (pending) => ({
      ...pending,
      messages: [
        ...pending.messages,
        ...nextMessages,
      ],
    }))
  }

  function appendPendingToolResult(sessionId: string, event: AgentTraceEvent) {
    const state = pendingState(sessionId)
    if (!state) {
      return
    }

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
    const alreadyHasResult = state.messages.some((message) => (
      message.role === 'tool' && message.tool_call_id === resultId
    ))
    if (alreadyHasResult) {
      return
    }

    updatePendingState(sessionId, (pending) => ({
      ...pending,
      messages: [
        ...pending.messages,
        toolMessage,
      ],
    }))
  }

  function markPendingToolCallDone(sessionId: string, toolCallId: string) {
    updatePendingState(sessionId, (state) => ({
      ...state,
      messages: state.messages.map((message) => {
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
      }),
    }))
  }

  function appendPendingAssistantText(sessionId: string, text: string) {
    if (!text) {
      return
    }

    const state = pendingState(sessionId)
    if (!state) {
      return
    }

    const assistant = state.messages.find((message) => message.role === 'assistant')
    const current = assistant?.pending
      && state.assistantHasDelta
      ? assistant.text
      : ''
    setPendingAssistantHasDelta(sessionId, true)
    setPendingAssistantText(sessionId, current + text, true)
  }

  function setPendingAssistantText(sessionId: string, text: string, pending: boolean) {
    const state = pendingState(sessionId)
    if (!state) {
      return
    }

    const messages = state.messages.filter((message) => message.role !== 'assistant')
    if (messages.length === state.messages.length && state.messages.length > 0) {
      return
    }

    updatePendingState(sessionId, (pendingState) => ({
      ...pendingState,
      messages: [
        ...messages,
        {
          role: 'assistant',
          content: [{ type: 'text', text }],
          text,
          pending,
        },
      ],
    }))
  }

  function markPendingAssistantDone(sessionId: string) {
    const assistant = pendingState(sessionId)?.messages.find((message) => message.role === 'assistant')
    if (!assistant) {
      return
    }

    setPendingAssistantText(sessionId, assistant.text, false)
  }

  function clearPendingMessages(sessionId: string | null = selectedSessionId.value) {
    if (sessionId === null) {
      return
    }

    const { [sessionId]: _removed, ...remaining } = pendingChatStates.value
    pendingChatStates.value = remaining
  }

  function removePendingApproval(approvalId: string) {
    updateAllPendingStates((state) => ({
      ...state,
      messages: state.messages.filter((message) => {
        const approval = message.metadata?.approval_request
        return !(isApprovalRequest(approval) && approval.approval_id === approvalId)
      }),
    }))
  }

  function hideApproval(approvalId: string) {
    hiddenApprovalIds.value = new Set(hiddenApprovalIds.value).add(approvalId)
    removePendingApproval(approvalId)
  }

  function showApproval(approvalId: string) {
    const next = new Set(hiddenApprovalIds.value)
    next.delete(approvalId)
    hiddenApprovalIds.value = next
  }

  function clearPendingApprovalArtifacts(sessionId: string, toolCallId: string) {
    updatePendingState(sessionId, (state) => ({
      ...state,
      messages: state.messages.filter((message) => {
        if (message.role === 'assistant' && message.pending) {
          return false
        }
        if (!message.pending) {
          return true
        }
        return !(message.tool_calls || []).some((call) => (
          call.tool_call_id === toolCallId
        ))
      }),
      assistantHasDelta: false,
    }))
  }

  function pendingState(sessionId: string): PendingChatState | null {
    return pendingChatStates.value[sessionId] || null
  }

  function isSessionSending(sessionId: string): boolean {
    return pendingState(sessionId)?.sending === true
  }

  function setPendingState(sessionId: string, state: PendingChatState) {
    pendingChatStates.value = {
      ...pendingChatStates.value,
      [sessionId]: state,
    }
  }

  function updatePendingState(
    sessionId: string,
    update: (state: PendingChatState) => PendingChatState,
  ) {
    const state = pendingState(sessionId)
    if (!state) {
      return
    }

    setPendingState(sessionId, update(state))
  }

  function updateAllPendingStates(update: (state: PendingChatState) => PendingChatState) {
    pendingChatStates.value = Object.fromEntries(
      Object.entries(pendingChatStates.value).map(([sessionId, state]) => [
        sessionId,
        update(state),
      ]),
    )
  }

  function setPendingAssistantHasDelta(sessionId: string, value: boolean) {
    updatePendingState(sessionId, (state) => ({
      ...state,
      assistantHasDelta: value,
    }))
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
          .filter((approval) => !hiddenApprovalIds.value.has(approval.approval_id))
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
