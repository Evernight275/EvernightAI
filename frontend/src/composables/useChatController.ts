import { computed, ref, type ComputedRef, type Ref } from 'vue'
import {
  chatWithContextStream,
  chatWithSession,
  createContext,
  createSession,
  deleteSession,
  getContext,
  replaceSession,
  startAgentRunStream,
  startSessionAgentRun,
  type AgentRunState,
  type AgentTraceEvent,
  type ChatStreamEvent,
  type Content,
  type Context,
  type Session,
} from '../api'
import { textPart } from '../format'
import type { ProviderModelChoice } from './useProviderModels'

export type ChatDisplayMessage = Content & {
  outgoing?: boolean
  text: string
  pending?: boolean
  contextIndex?: number
}

type UseChatControllerOptions = {
  sessions: Ref<Session[]>
  sortedSessions: ComputedRef<Session[]>
  latestRun: ComputedRef<AgentRunState | undefined>
  selectedProviderModelChoice: ComputedRef<ProviderModelChoice>
  dashboardError: Ref<string | null>
  refreshDashboard: () => Promise<void>
  syncProviderModelFromSession: (session: Session) => void
}

export function useChatController({
  sessions,
  sortedSessions,
  latestRun,
  selectedProviderModelChoice,
  dashboardError,
  refreshDashboard,
  syncProviderModelFromSession,
}: UseChatControllerOptions) {
  const selectedSessionId = ref<string | null>(null)
  const selectedContext = ref<Context | null>(null)
  const contextLoading = ref(false)
  const chatDraft = ref('')
  const pendingChatMessages = ref<ChatDisplayMessage[]>([])
  const pendingChatSessionId = ref<string | null>(null)
  const pendingAssistantHasDelta = ref(false)
  const chatTimeoutSeconds = ref(30)
  const chatStreamEnabled = ref(false)
  const chatAgentEnabled = ref(true)
  const sendingMessage = ref(false)
  const creatingSession = ref(false)
  const chatError = ref<string | null>(null)

  const selectedSession = computed(() => (
    sessions.value.find((session) => session.session_id === selectedSessionId.value) || null
  ))

  const chatDisplayError = computed(() => chatError.value || dashboardError.value)

  const chatMessages = computed<ChatDisplayMessage[]>(() => {
    const pendingMessages = pendingChatSessionId.value === selectedSessionId.value
      ? pendingChatMessages.value
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
        ...pendingMessages,
      ]
    }

    const messages: ChatDisplayMessage[] = [...pendingMessages]

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
    const session = selectedSession.value
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
        metadata: {
          source: 'frontend-chat',
          timeout_seconds: chatTimeoutSeconds.value,
          stream: chatStreamEnabled.value,
        },
      }

      if (chatStreamEnabled.value && chatAgentEnabled.value) {
        const runId = newId('run')
        await startAgentRunStream({
          ...request,
          context_id: session.context_id,
          metadata: {
            ...request.metadata,
            session_id: session.session_id,
            run_id: runId,
          },
          max_tool_rounds: 1,
          recover_tool_errors: true,
          write_memory: false,
          pause_on_approval: false,
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
        await startSessionAgentRun(session.session_id, {
          ...request,
          max_tool_rounds: 1,
          recover_tool_errors: true,
          write_memory: false,
          pause_on_approval: false,
        })
      } else {
        await chatWithSession(session.session_id, request)
      }
      await refreshDashboard()
      clearPendingMessages()
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
    }
  }

  async function createNewChatSession() {
    creatingSession.value = true
    chatError.value = null

    const contextId = newId('ctx')
    const sessionId = newId('session')
    const providerId = selectedProviderModelChoice.value.providerId
    const modelId = selectedProviderModelChoice.value.modelId

    try {
      await createContext({
        context_id: contextId,
        messages: [],
      })
      await createSession({
        session_id: sessionId,
        title: '新会话',
        context_id: contextId,
        provider_id: providerId,
        model_id: modelId,
      })
      selectedSessionId.value = sessionId
      selectedContext.value = {
        context_id: contextId,
        messages: [],
      }
      clearPendingMessages()
      chatDraft.value = ''
      await refreshDashboard()
    } catch (error) {
      chatError.value = error instanceof Error ? error.message : '新建会话失败'
    } finally {
      creatingSession.value = false
    }
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
    } catch (error) {
      chatError.value = error instanceof Error ? error.message : '重命名会话失败'
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
    } catch (error) {
      chatError.value = error instanceof Error ? error.message : '删除会话失败'
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
      return
    }

    if (event.event_type === 'tool_completed' && event.summary) {
      setPendingAssistantText(event.summary, true)
      pendingAssistantHasDelta.value = false
      return
    }

    if (event.event_type === 'run_stopped') {
      markPendingAssistantDone()
      return
    }

    if (event.event_type === 'run_paused' && event.summary) {
      setPendingAssistantText(event.summary, false)
    }
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
    creatingSession,
    chatDisplayError,
    chatMessages,
    selectSession,
    loadSelectedContext,
    sendChatMessage,
    retryChatMessage,
    createNewChatSession,
    renameSession,
    removeSession,
    ensureSelectedSession,
  }
}

function isActiveMessage(message: Content): boolean {
  return message.status === undefined || message.status === null || message.status === 'active'
}

function newId(prefix: string): string {
  if (crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID()}`
  }

  return `${prefix}-${Date.now()}`
}
