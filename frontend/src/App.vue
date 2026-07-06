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
import AgentRunTraceDetail from './components/AgentRunTraceDetail.vue'
import AppHeader from './components/AppHeader.vue'
import AppSidebar from './components/AppSidebar.vue'
import ChatWorkspace from './components/ChatWorkspace.vue'
import DataAnalysisDashboard from './components/DataAnalysisDashboard.vue'
import Icon from './components/Icon.vue'
import LogTerminal from './components/LogTerminal.vue'
import ToolList from './components/ToolList.vue'
import ToastContainer from './components/ToastContainer.vue'
import { useChatController } from './composables/useChatController'
import { useProviderModels } from './composables/useProviderModels'
import { toast } from './composables/useToast'

type ViewKey = 'workbench' | 'chat' | 'tools' | 'runs' | 'analytics' | 'agents' | 'memories' | 'logs'

const viewMeta: Record<ViewKey, { title: string; description: string }> = {
  workbench: {
    title: '主页',
    description: '左侧是重要入口，上方是当前项目相关上下文，主体看会话、工具与执行流',
  },
  chat: {
    title: '聊天',
    description: '选择会话、查看上下文，并向当前会话发送消息',
  },
  tools: {
    title: '工具列表',
    description: '查看后端 runtime 已注册的工具和审批要求',
  },
  runs: {
    title: '运行队列',
    description: '查看 Agent run 状态、模型、工具轮次和最近输出',
  },
  analytics: {
    title: '数据统计',
    description: '查看 Agent、会话、工具调用和记忆写入的运行统计',
  },
  agents: {
    title: '模型提供商配置',
    description: '查看已注册 provider，并主动拉取每个 provider 暴露的模型',
  },
  memories: {
    title: '记忆库',
    description: '查看持久记忆入口，后续会接入查询和编辑',
  },
  logs: {
    title: '日志',
    description: '查看运行事件和系统日志入口',
  },
}

const viewStorageKey = 'evernight.currentView'
const viewKeys = Object.keys(viewMeta) as ViewKey[]

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
const runPageSizeOptions = [10, 25, 50]
const runPage = ref(1)
const runPageSize = ref(runPageSizeOptions[0])
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
  providerModelCount,
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
} = useChatController({
  sessions,
  sortedSessions,
  latestRun,
  tools,
  selectedProviderModelChoice,
  dashboardError,
  refreshDashboard,
  syncProviderModelFromSession,
})

const enabledProviderCount = computed(() => (
  providers.value.filter((provider) => provider.is_enabled !== false).length
))
const memoryStatus = computed(() => healthOk.value ? '已同步' : '未连接')
const pageTitle = computed(() => viewMeta[currentView.value].title)
const pageDescription = computed(() => viewMeta[currentView.value].description)
const runPageCount = computed(() => Math.max(1, Math.ceil(runs.value.length / runPageSize.value)))
const runPageStart = computed(() => runs.value.length === 0 ? 0 : (runPage.value - 1) * runPageSize.value + 1)
const runPageEnd = computed(() => Math.min(runs.value.length, runPage.value * runPageSize.value))
const pagedRuns = computed(() => {
  const start = (runPage.value - 1) * runPageSize.value
  return runs.value.slice(start, start + runPageSize.value)
})
const selectedRun = computed(() => (
  runs.value.find((run) => run.run_id === selectedRunId.value)
  || pagedRuns.value[0]
  || runs.value[0]
  || null
))

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

function setRunPage(nextPage: number) {
  runPage.value = Math.min(Math.max(nextPage, 1), runPageCount.value)
}

function selectRun(run: AgentRunState) {
  selectedRunId.value = run.run_id
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
  if (selectedRun.value?.run_id) {
    runIds.add(selectedRun.value.run_id)
  }
  for (const run of runs.value) {
    if (run.status === 'running' || run.status === 'paused') {
      runIds.add(run.run_id)
    }
  }
  runIds.forEach((runId) => {
    const run = runs.value.find((item) => item.run_id === runId)
    agentRunSocket?.subscribeRun(runId, run?.trace?.length || 0)
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

watch([runs, runPageSize], () => {
  setRunPage(runPage.value)
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
  <div class="app" :class="{ 'is-chat-view': currentView === 'chat' }">
    <ToastContainer ref="toastContainer" />
    <AppHeader @configure-api-key="configureApiKey" />

    <div class="shell">
      <AppSidebar :current-view="currentView" @navigate="navigate" />

      <main class="main">
        <section v-if="currentView !== 'chat'" class="page-head">
          <div>
            <h1>{{ pageTitle }}</h1>
            <p>{{ pageDescription }}</p>
          </div>
        </section>

        <section v-if="currentView === 'workbench'" class="home-welcome">
          <h2>欢迎使用 EvernightAI</h2>
          <p>一个强大的 AI Agent 运行时平台，支持多模型、工具调用和会话管理</p>

          <div class="quick-start-grid">
            <button class="quick-start-card" @click="navigate('chat')">
              <Icon name="message-circle" class="icon" />
              <h3>开始对话</h3>
              <p>创建新会话或继续现有对话，体验 AI 助手的强大能力</p>
            </button>

            <button class="quick-start-card" @click="navigate('tools')">
              <Icon name="tool" class="icon" />
              <h3>查看工具</h3>
              <p>浏览已注册的工具列表，了解 Agent 可以调用的功能</p>
            </button>

            <button class="quick-start-card" @click="navigate('agents')">
              <Icon name="cpu" class="icon" />
              <h3>配置模型</h3>
              <p>管理模型提供商，选择适合你任务的 AI 模型</p>
            </button>

            <button class="quick-start-card" @click="navigate('analytics')">
              <Icon name="activity" class="icon" />
              <h3>查看统计</h3>
              <p>查看 Agent run、会话、工具调用和记忆写入数据</p>
            </button>
          </div>
        </section>

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
          :creating-session="creatingSession"
          :disabled="providerModelChoices.length === 0"
          :error="chatDisplayError"
          :title="selectedSession?.title || selectedSession?.session_id || '聊天'"
          @select="selectSession"
          @send="sendChatMessage"
          @retry-message="retryChatMessage"
          @create-session="createNewChatSession"
          @rename-session="renameSession"
          @delete-session="removeSession"
        />

        <section v-else-if="currentView === 'tools'" class="content-grid">
          <div class="primary-stack">
            <ToolList :tools="tools" />
          </div>
          <aside class="side-stack">
            <section class="panel view-panel">
              <div class="panel-head">
                <h2><Icon name="shield-check" /><span>工具状态</span></h2>
                <span>{{ tools.length }} 个</span>
              </div>
              <p>工具来自后端 runtime 注册表。敏感工具会在 Agent run 中进入审批流程。</p>
            </section>
          </aside>
        </section>

        <section v-else-if="currentView === 'runs'" class="run-workbench" aria-label="运行队列">
          <div class="table-wrap run-table-panel">
            <div class="panel-head table-head">
              <h2><Icon name="activity" /><span>运行队列</span></h2>
              <div class="run-table-controls">
                <span>{{ runPageStart }}-{{ runPageEnd }} / {{ runs.length }} 条</span>
                <label class="run-page-size">
                  <span>每页</span>
                  <select v-model.number="runPageSize" aria-label="运行队列每页显示数量">
                    <option v-for="size in runPageSizeOptions" :key="size" :value="size">
                      {{ size }}
                    </option>
                  </select>
                </label>
              </div>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Provider / 模型</th>
                  <th>状态</th>
                  <th>工具轮次</th>
                  <th>Trace</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="runs.length === 0">
                  <td colspan="5" style="text-align: center; padding: 32px;">
                    <div style="display: inline-grid; gap: 8px; place-items: center;">
                      <Icon name="activity" style="width: 32px; height: 32px; color: var(--muted);" />
                      <strong style="color: var(--ink);">暂无运行记录</strong>
                      <span style="color: var(--muted); font-size: 13px;">Agent 运行后将在此显示</span>
                    </div>
                  </td>
                </tr>
                <tr
                  v-for="run in pagedRuns"
                  v-else
                  :key="run.run_id"
                  class="run-row"
                  :class="{ 'is-selected': selectedRun?.run_id === run.run_id }"
                  tabindex="0"
                  @click="selectRun(run)"
                  @keydown.enter.prevent="selectRun(run)"
                >
                  <td>
                    <span class="run-id">{{ run.run_id }}</span>
                  </td>
                  <td>
                    <div class="run-provider-cell">
                      <strong>{{ run.request.provider_id }}</strong>
                      <span>{{ run.request.model_id }}</span>
                    </div>
                  </td>
                  <td><span class="tag">{{ run.status || '未知' }}</span></td>
                  <td>{{ run.tool_rounds_used ?? 0 }} / {{ run.request.max_tool_rounds ?? 0 }}</td>
                  <td>{{ run.trace?.length ?? 0 }}</td>
                </tr>
              </tbody>
            </table>
            <div class="run-pagination" aria-label="运行队列分页">
              <button
                class="button compact-button icon-button"
                type="button"
                :disabled="runPage <= 1"
                title="上一页"
                aria-label="上一页"
                @click="setRunPage(runPage - 1)"
              >
                <Icon name="chevron-left" />
              </button>
              <span>第 {{ runPage }} / {{ runPageCount }} 页</span>
              <button
                class="button compact-button icon-button"
                type="button"
                :disabled="runPage >= runPageCount"
                title="下一页"
                aria-label="下一页"
                @click="setRunPage(runPage + 1)"
              >
                <Icon name="chevron-right" />
              </button>
            </div>
          </div>

          <AgentRunTraceDetail
            :run="selectedRun"
            :socket-status="agentRunSocketStatus"
            @pause="pauseRun"
            @cancel="cancelRun"
            @resume="resumeRun"
          />
        </section>

        <DataAnalysisDashboard v-else-if="currentView === 'analytics'" />

        <section v-else-if="currentView === 'agents'" class="provider-config" aria-label="模型提供商配置">
          <div class="panel-head">
            <h2><Icon name="table-2" /><span>模型提供商配置</span></h2>
            <div class="panel-head-actions">
              <span>{{ enabledProviderCount }}/{{ providers.length }} 个 provider · {{ providerModelCount }} 个模型</span>
              <button
                class="button compact-button primary"
                :class="{ 'is-spinning': providerModelsLoading }"
                type="button"
                :disabled="providerModelsLoading"
                @click="refreshProviderModels"
              >
                <Icon name="activity" />
                <span>{{ providerModelsLoading ? '拉取中' : '刷新模型' }}</span>
              </button>
            </div>
          </div>
          <div class="provider-summary">
            <span>当前聊天模型：{{ selectedProviderModelChoice.label }}</span>
            <span>{{ providerModelsUpdatedAt ? `最近刷新：${providerModelsUpdatedAt}` : '等待刷新' }}</span>
          </div>
          <p v-if="providerModelsError" class="provider-error">{{ providerModelsError }}</p>
          <div v-if="providers.length === 0" class="provider-empty">
            <Icon name="inbox" class="empty-state-icon" />
            <div class="empty-state-text">
              <strong>暂无模型提供商</strong>
              <span>请检查后端配置，确保至少有一个模型提供商已启用</span>
            </div>
          </div>
          <div v-else class="provider-list">
            <article
              v-for="group in providerModelGroups"
              :key="group.provider.provider_id"
              class="provider-row"
            >
              <div class="provider-row-main">
                <div>
                  <h3>{{ group.provider.name }}</h3>
                  <p>{{ group.provider.provider_id }} · {{ group.provider.type }}</p>
                </div>
                <span class="tag">{{ group.provider.is_enabled === false ? '停用' : '启用' }}</span>
              </div>
              <div class="provider-models">
                <span v-if="group.models.length === 0" class="provider-model-empty">
                  未发现模型
                </span>
                <button
                  v-for="model in group.models"
                  v-else
                  :key="model.model_id"
                  class="model-chip"
                  :class="{ 'is-selected': selectedProviderModel === `${group.provider.provider_id}::${model.model_id}` }"
                  type="button"
                  @click="selectedProviderModel = `${group.provider.provider_id}::${model.model_id}`"
                >
                  {{ model.model_id }}
                </button>
              </div>
            </article>
          </div>
        </section>

        <section v-else-if="currentView === 'memories'" class="panel view-panel">
          <div class="panel-head">
            <h2><Icon name="database" /><span>记忆库</span></h2>
            <span>{{ memoryStatus }}</span>
          </div>
          <div style="min-height: 280px; display: grid; place-items: center;">
            <div style="display: grid; gap: 16px; place-items: center; text-align: center; max-width: 420px;">
              <Icon name="database" style="width: 48px; height: 48px; padding: 12px; border-radius: 12px; background: var(--primary-light); color: var(--primary);" />
              <div>
                <strong style="display: block; font-size: 16px; margin-bottom: 8px; color: var(--ink);">记忆库功能即将推出</strong>
                <p style="margin: 0; line-height: 1.6;">记忆库将支持查看、搜索和管理 Agent 的持久化记忆。您可以在这里筛选记忆条目、查看详细内容，以及删除不需要的记忆。</p>
              </div>
              <button class="button primary" disabled>
                <Icon name="plus" />
                <span>添加记忆（敬请期待）</span>
              </button>
            </div>
          </div>
        </section>

        <LogTerminal v-else />

      </main>
    </div>
  </div>
</template>
