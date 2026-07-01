<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchDashboard,
  fetchProviderModels,
  getApiKey,
  setApiKey,
  type AgentRunState,
  type ProviderInfo,
  type ProviderModelGroup,
  type Session,
  type ToolDefinition,
} from './api'
import AppHeader from './components/AppHeader.vue'
import AppSidebar from './components/AppSidebar.vue'
import ChatWorkspace from './components/ChatWorkspace.vue'
import Icon from './components/Icon.vue'
import LogTerminal from './components/LogTerminal.vue'
import ToolList from './components/ToolList.vue'
import { useChatController } from './composables/useChatController'
import { useProviderModels } from './composables/useProviderModels'

type ViewKey = 'workbench' | 'chat' | 'tools' | 'runs' | 'agents' | 'memories' | 'logs'

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
const runPageSizeOptions = [10, 25, 50]
const runPage = ref(1)
const runPageSize = ref(runPageSizeOptions[0])
const providerModelsLoading = ref(false)
const dashboardError = ref<string | null>(null)
const providerModelsError = ref<string | null>(null)
const providerModelsUpdatedAt = ref('')

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
  if (currentView.value === 'agents') {
    await refreshProviderModels()
  }
})

watch(currentView, async (view) => {
  if (view === 'agents') {
    await refreshProviderModels()
  }
})

watch([runs, runPageSize], () => {
  setRunPage(runPage.value)
})
</script>

<template>
  <div class="app" :class="{ 'is-chat-view': currentView === 'chat' }">
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
          :disabled="!selectedSession"
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

        <section v-else-if="currentView === 'runs'" class="table-wrap" aria-label="运行队列">
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
                <th>模型</th>
                <th>状态</th>
                <th>工具轮次</th>
                <th>剩余轮次</th>
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
              <tr v-for="run in pagedRuns" v-else :key="run.run_id">
                <td>{{ run.run_id }}</td>
                <td>{{ run.request.model_id }}</td>
                <td><span class="tag">{{ run.status || '未知' }}</span></td>
                <td>{{ run.tool_rounds_used ?? 0 }}</td>
                <td>{{ run.remaining_tool_rounds ?? 0 }}</td>
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
        </section>

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
