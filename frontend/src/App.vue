<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  AgentRunSocketClient,
  fetchDashboard,
  fetchProviderModels,
  getApiKey,
  getAgentRun,
  setApiKey,
  type AgentRunSocketStatus,
  type AgentRunState,
  type AgentTraceEvent,
  type ProviderInfo,
  type ProviderModelGroup,
  type Session,
  type ToolDefinition,
  type WebSocketTracePayload,
} from './api'
import AppHeader from './components/AppHeader.vue'
import AppSidebar from './components/AppSidebar.vue'
import ChatWorkspace from './components/ChatWorkspace.vue'
import DataAnalysisDashboard from './components/DataAnalysisDashboard.vue'
import LogTerminal from './components/LogTerminal.vue'
import ToastContainer from './components/ToastContainer.vue'
import { useChatController } from './composables/useChatController'
import { useProviderModels } from './composables/useProviderModels'
import { toast } from './composables/useToast'
import AgentRunsView from './views/AgentRunsView.vue'
import MemoriesView from './views/MemoriesView.vue'
import ProvidersView from './views/ProvidersView.vue'
import ToolsView from './views/ToolsView.vue'
import WorkbenchView from './views/WorkbenchView.vue'
import { viewKeys, type ViewKey } from './views/navigation'

const viewStorageKey = 'evernight.currentView'

function readStoredView(): ViewKey {
  const storedView = localStorage.getItem(viewStorageKey)
  return viewKeys.includes(storedView as ViewKey) ? storedView as ViewKey : 'workbench'
}

function writeStoredView(view: ViewKey) {
  localStorage.setItem(viewStorageKey, view)
}

const currentView = ref<ViewKey>(readStoredView())
const healthOk = ref(false)
const sessions = ref<Session[]>([])
const providers = ref<ProviderInfo[]>([])
const providerModelGroups = ref<ProviderModelGroup[]>([])
const tools = ref<ToolDefinition[]>([])
const runs = ref<AgentRunState[]>([])
const selectedRunId = ref<string | null>(null)
const agentRunSocketStatus = ref<AgentRunSocketStatus>('disconnected')
const providerModelsLoading = ref(false)
const dashboardError = ref<string | null>(null)
const providerModelsError = ref<string | null>(null)
const providerModelsUpdatedAt = ref('')
const toastContainer = ref<InstanceType<typeof ToastContainer> | null>(null)
let agentRunSocket: AgentRunSocketClient | null = null

const sortedSessions = computed(() => (
  [...sessions.value]
    .sort((left, right) => timestamp(right) - timestamp(left))
    .slice(0, 6)
))

const latestRun = computed(() => (
  runs.value.find((run) => run.response?.message) || runs.value[0]
))

const {
  selectedProviderModel,
  providerModelChoices,
  selectedProviderModelChoice,
  ensureSelectedProviderModel,
  syncProviderModelFromSession,
} = useProviderModels(providerModelGroups, sessions, latestRun)

const {
  selectedSessionId,
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
} = useChatController({
  sessions,
  sortedSessions,
  runs,
  latestRun,
  tools,
  selectedProviderModelChoice,
  dashboardError,
  refreshDashboard,
  syncProviderModelFromSession,
})

const memoryStatus = computed(() => healthOk.value ? '已同步' : '未连接')

async function refreshDashboard() {
  const dashboard = await fetchDashboard()
  healthOk.value = dashboard.healthOk
  sessions.value = dashboard.sessions
  providers.value = dashboard.providers
  providerModelGroups.value = dashboard.providerModelGroups
  tools.value = dashboard.tools
  runs.value = dashboard.runs
  dashboardError.value = dashboard.error
  ensureSelectedSession()
  ensureSelectedProviderModel()
  await loadSelectedContext()
  syncRunSubscriptions()
}

async function refreshProviderModels() {
  providerModelsLoading.value = true
  providerModelsError.value = null

  try {
    const next = await fetchProviderModels()
    providers.value = next.providers
    providerModelGroups.value = next.providerModelGroups
    providerModelsUpdatedAt.value = new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
    ensureSelectedProviderModel()
    toast.success('模型列表刷新成功')
  } catch (error) {
    providerModelsError.value = error instanceof Error ? error.message : '模型拉取失败'
    toast.error(providerModelsError.value)
  } finally {
    providerModelsLoading.value = false
  }
}

function timestamp(session: Session): number {
  return new Date(session.updated_at || session.created_at || 0).getTime()
}

function navigate(view: ViewKey) {
  currentView.value = view
  writeStoredView(view)
}

async function configureApiKey() {
  const nextApiKey = window.prompt(
    '输入 EvernightAI API Key。留空并确认会清除当前 Key。',
    getApiKey(),
  )

  if (nextApiKey === null) {
    return
  }

  setApiKey(nextApiKey)
  reconnectAgentRunSocket()
  await refreshDashboard()
}

function connectAgentRunSocket() {
  agentRunSocket?.close()
  agentRunSocket = new AgentRunSocketClient({
    onStatus(status) {
      agentRunSocketStatus.value = status
    },
    onTrace(runId, event, payload) {
      applyAgentTrace(runId, event, payload)
    },
    onError(error) {
      toast.error(error.error_message || error.error_type)
    },
  })
  agentRunSocket.connect()
  syncRunSubscriptions()
}

function reconnectAgentRunSocket() {
  connectAgentRunSocket()
}

function syncRunSubscriptions() {
  if (!agentRunSocket) {
    return
  }

  const runIds = new Set<string>()
  if (selectedRunId.value) {
    runIds.add(selectedRunId.value)
  }
  for (const run of runs.value) {
    if (run.status === 'running' || run.status === 'paused') {
      runIds.add(run.run_id)
    }
  }
  runIds.forEach((runId) => {
    const run = runs.value.find((item) => item.run_id === runId)
    const trace = run?.trace || []
    const cursor = trace.reduce(
      (sequence, event, index) => Math.max(sequence, event.sequence || index + 1),
      0,
    )
    agentRunSocket?.subscribeRun(runId, cursor)
  })
}

function applyAgentTrace(
  runId: string,
  event: AgentTraceEvent,
  payload: WebSocketTracePayload,
) {
  const runIndex = runs.value.findIndex((run) => run.run_id === runId)
  if (runIndex === -1) {
    void refreshRun(runId)
    return
  }

  const run = runs.value[runIndex]
  const trace = [...(run.trace || [])]
  if (payload.sequence && payload.sequence > 0) {
    trace[payload.sequence - 1] = event
  } else {
    trace.push(event)
  }

  const nextRun: AgentRunState = {
    ...run,
    trace: trace.filter(Boolean),
    status: statusAfterTrace(run.status, event),
  }
  runs.value.splice(runIndex, 1, nextRun)

  if (event.event_type === 'run_paused' || event.event_type === 'run_stopped') {
    void refreshRun(runId)
  }
}

function statusAfterTrace(
  currentStatus: AgentRunState['status'],
  event: AgentTraceEvent,
): AgentRunState['status'] {
  if (event.event_type === 'run_started') {
    return 'running'
  }
  if (event.event_type === 'run_paused') {
    return 'paused'
  }
  if (event.event_type === 'run_stopped') {
    return event.metadata?.reason === 'canceled' ? 'canceled' : 'finished'
  }
  if (event.event_type === 'tool_failed' && currentStatus === 'failed') {
    return 'failed'
  }

  return currentStatus
}

async function refreshRun(runId: string) {
  try {
    const nextRun = await getAgentRun(runId)
    upsertRun(nextRun)
  } catch {
    // The run may have been pruned or hidden by auth; keep the local trace.
  }
}

function upsertRun(nextRun: AgentRunState) {
  const runIndex = runs.value.findIndex((run) => run.run_id === nextRun.run_id)
  if (runIndex === -1) {
    runs.value = [nextRun, ...runs.value]
    return
  }
  runs.value.splice(runIndex, 1, nextRun)
}

function pauseRun(run: AgentRunState) {
  agentRunSocket?.controlRun(run.run_id, 'pause', 'frontend pause')
}

function cancelRun(run: AgentRunState) {
  agentRunSocket?.controlRun(run.run_id, 'cancel', 'frontend cancel')
}

function resumeRun(run: AgentRunState) {
  agentRunSocket?.controlRun(run.run_id, 'resume')
}

onMounted(async () => {
  // 初始化 Toast 服务
  if (toastContainer.value) {
    toast.setHandler({
      success: toastContainer.value.success,
      error: toastContainer.value.error,
      warning: toastContainer.value.warning,
      info: toastContainer.value.info,
    })
  }

  await refreshDashboard()
  connectAgentRunSocket()
  if (currentView.value === 'agents') {
    await refreshProviderModels()
  }
})

onUnmounted(() => {
  agentRunSocket?.close()
})

watch(currentView, async (view) => {
  if (view === 'agents') {
    await refreshProviderModels()
  }
})

watch(runs, () => {
  if (!selectedRunId.value || !runs.value.some((run) => run.run_id === selectedRunId.value)) {
    selectedRunId.value = runs.value[0]?.run_id || null
  }
  syncRunSubscriptions()
})

watch(selectedRunId, () => {
  syncRunSubscriptions()
})
</script>

<template>
  <div
    class="app"
    :class="{
      'is-chat-view': currentView === 'chat',
      'is-workbench-view': currentView === 'workbench',
    }"
  >
    <ToastContainer ref="toastContainer" />
    <AppHeader :health-ok="healthOk" @configure-api-key="configureApiKey" />

    <div class="shell">
      <AppSidebar :current-view="currentView" @navigate="navigate" />

      <main class="main">
        <WorkbenchView v-if="currentView === 'workbench'" />

        <ChatWorkspace
          v-else-if="currentView === 'chat'"
          v-model="chatDraft"
          v-model:model-selection="selectedProviderModel"
          v-model:timeout-seconds="chatTimeoutSeconds"
          v-model:stream-enabled="chatStreamEnabled"
          v-model:agent-enabled="chatAgentEnabled"
          :sessions="sortedSessions"
          :model-options="providerModelChoices"
          :selected-session-id="selectedSessionId"
          :messages="chatMessages"
          :loading="contextLoading"
          :sending="sendingMessage"
          :approving-approval="approvingToolApproval"
          :creating-session="creatingSession"
          :disabled="providerModelChoices.length === 0"
          :error="chatDisplayError"
          :title="selectedSession?.title || selectedSession?.session_id || '聊天'"
          @select="selectSession"
          @send="sendChatMessage"
          @approve-tool-approval="(message) => decideToolApproval(message, 'approved')"
          @deny-tool-approval="(message) => decideToolApproval(message, 'denied')"
          @retry-message="retryChatMessage"
          @create-session="createNewChatSession"
          @rename-session="renameSession"
          @delete-session="removeSession"
        />

        <ToolsView v-else-if="currentView === 'tools'" :tools="tools" />

        <AgentRunsView
          v-else-if="currentView === 'runs'"
          v-model:selected-run-id="selectedRunId"
          :runs="runs"
          :socket-status="agentRunSocketStatus"
          @pause="pauseRun"
          @cancel="cancelRun"
          @resume="resumeRun"
        />

        <DataAnalysisDashboard v-else-if="currentView === 'analytics'" />

        <ProvidersView
          v-else-if="currentView === 'agents'"
          v-model:selected-provider-model="selectedProviderModel"
          :providers="providers"
          :provider-model-groups="providerModelGroups"
          :selected-model-label="selectedProviderModelChoice.label"
          :loading="providerModelsLoading"
          :error="providerModelsError"
          :updated-at="providerModelsUpdatedAt"
          @refresh="refreshProviderModels"
        />

        <MemoriesView v-else-if="currentView === 'memories'" :status="memoryStatus" />

        <LogTerminal v-else />

      </main>
    </div>
  </div>
</template>
