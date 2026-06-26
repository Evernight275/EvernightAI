<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  chatWithSession,
  createContext,
  createSession,
  fetchDashboard,
  fetchProviderModels,
  getApiKey,
  getContext,
  setApiKey,
  type AgentRunState,
  type Content,
  type Context,
  type ProviderInfo,
  type ProviderModelGroup,
  type Session,
  type ToolDefinition,
} from './api'
import { textPart } from './format'
import AppHeader from './components/AppHeader.vue'
import AppSidebar from './components/AppSidebar.vue'
import ChatWorkspace from './components/ChatWorkspace.vue'
import Icon from './components/Icon.vue'
import ToolList from './components/ToolList.vue'

type ViewKey = 'workbench' | 'chat' | 'tools' | 'runs' | 'agents' | 'memories' | 'logs'
type ProviderModelChoice = {
  value: string
  providerId: string
  modelId: string
  label: string
}

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

const currentView = ref<ViewKey>('workbench')
const healthOk = ref(false)
const sessions = ref<Session[]>([])
const providers = ref<ProviderInfo[]>([])
const providerModelGroups = ref<ProviderModelGroup[]>([])
const tools = ref<ToolDefinition[]>([])
const runs = ref<AgentRunState[]>([])
const selectedSessionId = ref<string | null>(null)
const selectedContext = ref<Context | null>(null)
const contextLoading = ref(false)
const chatDraft = ref('')
const selectedProviderModel = ref('main::gpt-4.1-mini')
const sendingMessage = ref(false)
const creatingSession = ref(false)
const providerModelsLoading = ref(false)
const chatError = ref<string | null>(null)
const dashboardError = ref<string | null>(null)
const providerModelsError = ref<string | null>(null)
const providerModelsUpdatedAt = ref('')
const defaultModelChoice: ProviderModelChoice = {
  value: 'main::gpt-4.1-mini',
  providerId: 'main',
  modelId: 'gpt-4.1-mini',
  label: 'main / gpt-4.1-mini',
}

const sortedSessions = computed(() => (
  [...sessions.value]
    .sort((left, right) => timestamp(right) - timestamp(left))
    .slice(0, 6)
))

const selectedSession = computed(() => (
  sessions.value.find((session) => session.session_id === selectedSessionId.value) || null
))

const latestRun = computed(() => (
  runs.value.find((run) => run.response?.message) || runs.value[0]
))

const providerModelChoices = computed<ProviderModelChoice[]>(() => {
  const choices = new Map<string, ProviderModelChoice>()

  providerModelGroups.value.forEach(({ provider, models }) => {
    models.forEach((model) => {
      addProviderModelChoice(choices, provider.provider_id, model.model_id, provider.name)
    })
  })

  if (choices.size === 0) {
    addProviderModelChoice(choices, defaultModelChoice.providerId, defaultModelChoice.modelId)
  }

  sessions.value.forEach((session) => {
    addProviderModelChoice(choices, session.provider_id, session.model_id)
  })

  if (latestRun.value?.request) {
    addProviderModelChoice(
      choices,
      latestRun.value.request.provider_id,
      latestRun.value.request.model_id,
    )
  }

  return [...choices.values()]
})

const selectedProviderModelChoice = computed(() => (
  providerModelChoices.value.find((choice) => choice.value === selectedProviderModel.value)
  || providerModelChoices.value[0]
  || defaultModelChoice
))

const providerModelCount = computed(() => (
  providerModelGroups.value.reduce((total, group) => total + group.models.length, 0)
))
const enabledProviderCount = computed(() => (
  providers.value.filter((provider) => provider.is_enabled !== false).length
))
const memoryStatus = computed(() => healthOk.value ? '已同步' : '未连接')
const pageTitle = computed(() => viewMeta[currentView.value].title)
const pageDescription = computed(() => viewMeta[currentView.value].description)
const chatDisplayError = computed(() => chatError.value || dashboardError.value)

const chatMessages = computed<Array<Content & { outgoing?: boolean; text: string }>>(() => {
  if (selectedContext.value?.messages?.length) {
    return selectedContext.value.messages.map((message) => ({
      ...message,
      text: textPart(message),
      outgoing: message.role === 'assistant',
    }))
  }

  const messages: Array<Content & { outgoing?: boolean; text: string }> = []

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
  } catch (error) {
    providerModelsError.value = error instanceof Error ? error.message : '模型拉取失败'
  } finally {
    providerModelsLoading.value = false
  }
}

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
  const session = selectedSession.value
  const messageText = text.trim()

  if (!session || messageText === '') {
    return
  }

  sendingMessage.value = true
  chatError.value = null

  try {
    await chatWithSession(session.session_id, {
      provider_id: selectedProviderModelChoice.value.providerId,
      model_id: selectedProviderModelChoice.value.modelId,
      messages: [
        {
          role: 'user',
          content: [{ type: 'text', text: messageText }],
        },
      ],
    })
    chatDraft.value = ''
    await refreshDashboard()
  } catch (error) {
    chatError.value = error instanceof Error ? error.message : '消息发送失败'
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
    chatDraft.value = ''
    await refreshDashboard()
  } catch (error) {
    chatError.value = error instanceof Error ? error.message : '新建会话失败'
  } finally {
    creatingSession.value = false
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

function ensureSelectedProviderModel() {
  if (
    providerModelChoices.value.some((choice) => choice.value === selectedProviderModel.value)
  ) {
    return
  }

  selectedProviderModel.value = providerModelChoices.value[0]?.value || defaultModelChoice.value
}

function addProviderModelChoice(
  choices: Map<string, ProviderModelChoice>,
  providerId: string | null | undefined,
  modelId: string | null | undefined,
  providerName?: string | null,
) {
  const cleanProviderId = providerId?.trim()
  const cleanModelId = modelId?.trim()

  if (!cleanProviderId || !cleanModelId) {
    return
  }

  const value = `${cleanProviderId}::${cleanModelId}`
  if (choices.has(value)) {
    return
  }

  choices.set(value, {
    value,
    providerId: cleanProviderId,
    modelId: cleanModelId,
    label: `${providerName?.trim() || cleanProviderId} / ${cleanModelId}`,
  })
}

function syncProviderModelFromSession(session: Session) {
  if (!session.provider_id || !session.model_id) {
    return
  }

  selectedProviderModel.value = `${session.provider_id}::${session.model_id}`
}

function timestamp(session: Session): number {
  return new Date(session.updated_at || session.created_at || 0).getTime()
}

function newId(prefix: string): string {
  if (crypto.randomUUID) {
    return `${prefix}-${crypto.randomUUID()}`
  }

  return `${prefix}-${Date.now()}`
}

function navigate(view: ViewKey) {
  currentView.value = view
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
  await refreshDashboard()
}

onMounted(async () => {
  await refreshDashboard()
})

watch(currentView, async (view) => {
  if (view === 'agents') {
    await refreshProviderModels()
  }
})
</script>

<template>
  <div class="app">
    <AppHeader @configure-api-key="configureApiKey" />

    <div class="shell">
      <AppSidebar :current-view="currentView" @navigate="navigate" />

      <main class="main">
        <section class="page-head">
          <div>
            <h1>{{ pageTitle }}</h1>
            <p>{{ pageDescription }}</p>
          </div>
        </section>

        <section v-if="currentView === 'workbench'" class="home-welcome">
          <h2>欢迎使用</h2>
        </section>

        <ChatWorkspace
          v-else-if="currentView === 'chat'"
          v-model="chatDraft"
          v-model:model-selection="selectedProviderModel"
          :sessions="sortedSessions"
          :model-options="providerModelChoices"
          :selected-session-id="selectedSessionId"
          :messages="chatMessages"
          :loading="contextLoading"
          :sending="sendingMessage"
          :creating-session="creatingSession"
          :disabled="!selectedSession"
          :error="chatDisplayError"
          :title="selectedSession?.title || selectedSession?.session_id || '聊天'"
          @select="selectSession"
          @send="sendChatMessage"
          @create-session="createNewChatSession"
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

        <section v-else-if="currentView === 'runs'" class="table-wrap" aria-label="运行队列">
          <div class="panel-head table-head">
            <h2><Icon name="activity" /><span>运行队列</span></h2>
            <span>{{ runs.length }} 条</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>模型</th>
                <th>状态</th>
                <th>工具轮次</th>
                <th>剩余轮次</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="runs.length === 0">
                <td>暂无运行</td>
                <td>-</td>
                <td><span class="tag">空</span></td>
                <td>-</td>
                <td>-</td>
              </tr>
              <tr v-for="run in runs" v-else :key="run.run_id">
                <td>{{ run.run_id }}</td>
                <td>{{ run.request.model_id }}</td>
                <td><span class="tag">{{ run.status || '未知' }}</span></td>
                <td>{{ run.tool_rounds_used ?? 0 }}</td>
                <td>{{ run.remaining_tool_rounds ?? 0 }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section v-else-if="currentView === 'agents'" class="provider-config" aria-label="模型提供商配置">
          <div class="panel-head">
            <h2><Icon name="table-2" /><span>模型提供商配置</span></h2>
            <div class="panel-head-actions">
              <span>{{ enabledProviderCount }}/{{ providers.length }} 个 provider · {{ providerModelCount }} 个模型</span>
              <button
                class="button compact-button"
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
            暂无模型提供商
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
          <p>记忆库页面先占位。下一步可以接入 `GET /memories`、筛选和删除。</p>
        </section>

        <section v-else class="panel view-panel">
          <div class="panel-head">
            <h2><Icon name="scroll-text" /><span>日志</span></h2>
            <span>待接入</span>
          </div>
          <p>日志页先占位。后续可从 Agent trace 或服务端日志流接入。</p>
        </section>

      </main>
    </div>
  </div>
</template>
