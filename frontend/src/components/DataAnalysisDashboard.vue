<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  listDataSources,
  runDataStatistics,
  type DataSourceDefinition,
  type DataStatisticsRequest,
  type DataStatisticsResult,
  type DataStatisticsRow,
} from '../api'
import Icon from './Icon.vue'

type StatisticPreset = {
  id: string
  title: string
  description: string
  icon: string
  sourceId: string
  request: DataStatisticsRequest
}

type StatisticCard = StatisticPreset & {
  error: string | null
  loading: boolean
  result: DataStatisticsResult | null
}

type LineChartPoint = {
  x: number
  y: number
  label: string
  value: number
}

const lineChartWidth = 1000
const lineChartHeight = 220
const lineChartPaddingX = 28
const lineChartPaddingY = 20

const statisticPresets: StatisticPreset[] = [
  {
    id: 'agent_runs_total',
    title: 'Agent run 总量',
    description: '累计 Agent run 数量',
    icon: 'activity',
    sourceId: 'agent_runs',
    request: {
      source_id: 'agent_runs',
      metrics: ['run_count'],
    },
  },
  {
    id: 'run_outcomes',
    title: '成功 / 失败 / 暂停',
    description: 'Agent run 状态占比',
    icon: 'shield-check',
    sourceId: 'agent_runs',
    request: {
      source_id: 'agent_runs',
      metrics: ['successful_run_rate', 'failed_run_rate', 'paused_run_rate'],
    },
  },
  {
    id: 'average_tool_rounds',
    title: '平均 tool rounds',
    description: '每次运行平均工具轮次',
    icon: 'wrench',
    sourceId: 'agent_runs',
    request: {
      source_id: 'agent_runs',
      metrics: ['average_tool_rounds'],
    },
  },
  {
    id: 'token_usage',
    title: 'Token 用量',
    description: '累计输入、输出和总 token',
    icon: 'database',
    sourceId: 'agent_runs',
    request: {
      source_id: 'agent_runs',
      metrics: [
        'prompt_tokens_total',
        'completion_tokens_total',
        'total_tokens_total',
        'cached_prompt_tokens_total',
        'cache_write_prompt_tokens_total',
        'cache_observed_prompt_tokens_total',
        'uncached_prompt_tokens_total',
      ],
    },
  },
  {
    id: 'daily_agent_runs',
    title: '每日 Agent run',
    description: '按创建日期统计 run 数量',
    icon: 'activity',
    sourceId: 'agent_runs',
    request: {
      source_id: 'agent_runs',
      metrics: ['run_count'],
      dimensions: ['created_day'],
      sorts: [{ field_id: 'created_day', direction: 'desc' }],
      limit: 14,
    },
  },
  {
    id: 'session_total',
    title: '会话总量',
    description: '累计会话数量',
    icon: 'message-square',
    sourceId: 'sessions',
    request: {
      source_id: 'sessions',
      metrics: ['session_count'],
    },
  },
  {
    id: 'daily_sessions',
    title: '每日新会话',
    description: '按创建日期统计新会话',
    icon: 'message-square',
    sourceId: 'sessions',
    request: {
      source_id: 'sessions',
      metrics: ['session_count'],
      dimensions: ['created_day'],
      sorts: [{ field_id: 'created_day', direction: 'asc' }],
      limit: 14,
    },
  },
  {
    id: 'provider_model_requests',
    title: 'Provider / Model 请求',
    description: '按 provider 和 model 分组统计 run 数',
    icon: 'table-2',
    sourceId: 'agent_runs',
    request: {
      source_id: 'agent_runs',
      metrics: ['run_count'],
      dimensions: ['provider_id', 'model_id'],
      sorts: [{ field_id: 'run_count', direction: 'desc' }],
      limit: 8,
    },
  },
  {
    id: 'provider_model_tokens',
    title: 'Provider / Model Token',
    description: '按 provider 和 model 聚合 token 用量',
    icon: 'table-2',
    sourceId: 'agent_runs',
    request: {
      source_id: 'agent_runs',
      metrics: [
        'prompt_tokens_total',
        'completion_tokens_total',
        'total_tokens_total',
        'cached_prompt_tokens_total',
        'cache_observed_prompt_tokens_total',
        'uncached_prompt_tokens_total',
      ],
      dimensions: ['provider_id', 'model_id'],
      sorts: [{ field_id: 'total_tokens_total', direction: 'desc' }],
      limit: 8,
    },
  },
  {
    id: 'context_messages',
    title: '上下文消息数',
    description: '平均上下文消息数量',
    icon: 'database',
    sourceId: 'contexts',
    request: {
      source_id: 'contexts',
      metrics: ['average_message_count'],
    },
  },
  {
    id: 'memory_write_sessions',
    title: '记忆写入会话',
    description: '有记忆写入的会话数量',
    icon: 'database',
    sourceId: 'agent_trace_events',
    request: {
      source_id: 'agent_trace_events',
      metrics: ['sessions_with_memory_write_count'],
    },
  },
  {
    id: 'tool_calls_by_tool',
    title: '工具调用',
    description: '按工具统计调用、成功、失败和审批',
    icon: 'wrench',
    sourceId: 'agent_trace_events',
    request: {
      source_id: 'agent_trace_events',
      metrics: [
        'tool_call_count',
        'tool_success_count',
        'tool_failure_count',
        'tool_approval_required_count',
      ],
      dimensions: ['tool_name'],
      sorts: [{ field_id: 'tool_call_count', direction: 'desc' }],
      limit: 8,
    },
  },
]

const sources = ref<DataSourceDefinition[]>([])
const cards = ref<StatisticCard[]>(statisticPresets.map((preset) => ({
  ...preset,
  error: null,
  loading: false,
  result: null,
})))
const loading = ref(false)
const loadError = ref<string | null>(null)
const updatedAt = ref('')

const sourceMap = computed(() => new Map(
  sources.value.map((source) => [source.source_id, source]),
))

const overviewTiles = computed(() => [
  {
    label: 'Agent runs',
    value: formatMetric(firstMetricValue('agent_runs_total', 'run_count'), 'run_count'),
    caption: sourceName('agent_runs'),
    icon: 'activity',
  },
  {
    label: '成功率',
    value: formatMetric(firstMetricValue('run_outcomes', 'successful_run_rate'), 'successful_run_rate'),
    caption: '失败 / 暂停也在下方展开',
    icon: 'shield-check',
  },
  {
    label: '会话',
    value: formatMetric(firstMetricValue('session_total', 'session_count'), 'session_count'),
    caption: sourceName('sessions'),
    icon: 'message-square',
  },
  {
    label: '工具调用',
    value: formatMetric(sumMetric('tool_calls_by_tool', 'tool_call_count'), 'tool_call_count'),
    caption: '按工具聚合',
    icon: 'wrench',
  },
  {
    label: 'Tokens',
    value: formatMetric(firstMetricValue('token_usage', 'total_tokens_total'), 'total_tokens_total'),
    caption: cacheHitRateLabel('token_usage'),
    icon: 'database',
  },
])

const dailyAgentRunLine = computed(() => {
  const data = [...rows('daily_agent_runs')].reverse().map((row) => ({
    label: dimensionLabel(row, ['created_day']),
    value: asNumber(row.metrics?.run_count) || 0,
  }))
  const maxValue = Math.max(...data.map((item) => item.value), 1)
  const plotWidth = lineChartWidth - lineChartPaddingX * 2
  const plotHeight = lineChartHeight - lineChartPaddingY * 2
  const points: LineChartPoint[] = data.map((item, index) => ({
    ...item,
    x: data.length === 1
      ? lineChartWidth / 2
      : lineChartPaddingX + (index / (data.length - 1)) * plotWidth,
    y: lineChartPaddingY + (1 - item.value / maxValue) * plotHeight,
  }))
  const polyline = points.map((point) => `${point.x},${point.y}`).join(' ')
  const baseline = lineChartHeight - lineChartPaddingY
  const areaPath = points.length === 0
    ? ''
    : `M ${points[0].x} ${baseline} L ${points.map((point) => `${point.x} ${point.y}`).join(' L ')} L ${points.at(-1)?.x || 0} ${baseline} Z`

  return {
    points,
    polyline,
    areaPath,
    maxValue,
    gridLines: [0, 0.25, 0.5, 0.75, 1].map((ratio) => (
      lineChartPaddingY + ratio * plotHeight
    )),
  }
})

onMounted(refreshAnalytics)

async function refreshAnalytics() {
  loading.value = true
  loadError.value = null

  try {
    sources.value = await listDataSources()
    await Promise.all(cards.value.map((card) => loadCard(card)))
    updatedAt.value = new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch (error) {
    loadError.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function loadCard(card: StatisticCard) {
  card.loading = true
  card.error = null
  card.result = null

  try {
    if (!sourceMap.value.has(card.sourceId)) {
      throw new Error(`缺少数据源 ${card.sourceId}`)
    }
    card.result = await runDataStatistics(card.request)
  } catch (error) {
    card.error = errorMessage(error)
  } finally {
    card.loading = false
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '数据统计请求失败'
}

function findCard(cardId: string): StatisticCard | undefined {
  return cards.value.find((card) => card.id === cardId)
}

function rows(cardId: string): DataStatisticsRow[] {
  return findCard(cardId)?.result?.rows || []
}

function cardError(cardId: string): string | null {
  return findCard(cardId)?.error || null
}

function firstMetricValue(cardId: string, metricId: string): unknown {
  return rows(cardId)[0]?.metrics?.[metricId]
}

function sumMetric(cardId: string, metricId: string): number | null {
  const values = rows(cardId).map((row) => asNumber(row.metrics?.[metricId]))
  const validValues = values.filter((value): value is number => value !== null)
  if (validValues.length === 0) {
    return firstMetricNumber(cardId, metricId)
  }

  return validValues.reduce((total, value) => total + value, 0)
}

function firstMetricNumber(cardId: string, metricId: string): number | null {
  return asNumber(firstMetricValue(cardId, metricId))
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }

  return null
}

function cacheHitRate(cardId: string, row?: DataStatisticsRow): number | null {
  const metrics = row?.metrics
  const cached = asNumber(
    metrics?.cached_prompt_tokens_total
      ?? firstMetricValue(cardId, 'cached_prompt_tokens_total'),
  )
  const observed = asNumber(
    metrics?.cache_observed_prompt_tokens_total
      ?? firstMetricValue(cardId, 'cache_observed_prompt_tokens_total'),
  )
  if (cached === null || observed === null || observed <= 0) {
    return null
  }

  return cached / observed
}

function cacheHitRateLabel(cardId: string, row?: DataStatisticsRow): string {
  const rate = cacheHitRate(cardId, row)
  return rate === null ? 'Provider 未报告缓存用量' : `缓存命中 ${(rate * 100).toFixed(1)}%`
}

function formatMetric(value: unknown, metricId: string): string {
  const numberValue = asNumber(value)
  if (numberValue === null) {
    return '-'
  }
  if (metricId.endsWith('_rate')) {
    return `${(numberValue * 100).toFixed(1)}%`
  }
  if (Math.abs(numberValue) < 10 && !Number.isInteger(numberValue)) {
    return numberValue.toFixed(2)
  }

  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: Number.isInteger(numberValue) ? 0 : 1,
  }).format(numberValue)
}

function sourceName(sourceId: string): string {
  return sourceMap.value.get(sourceId)?.name || sourceId
}

function dimensionLabel(row: DataStatisticsRow, dimensionIds: string[]): string {
  const dimensions = row.dimensions || {}
  const values = dimensionIds
    .map((dimensionId) => dimensions[dimensionId])
    .filter((value) => value !== undefined && value !== null && value !== '')
    .map(String)

  return values.length > 0 ? values.join(' · ') : '未分组'
}

function hasRows(cardId: string): boolean {
  return rows(cardId).length > 0
}
</script>

<template>
  <section class="analytics-dashboard" aria-label="数据统计分析">
    <div class="analytics-toolbar">
      <div>
        <h2><Icon name="chart-column" /><span>数据统计分析</span></h2>
        <p>{{ updatedAt ? `最近刷新：${updatedAt}` : '读取 runtime 内置数据源' }}</p>
      </div>
      <button
        class="button compact-button primary"
        :class="{ 'is-spinning': loading }"
        type="button"
        :disabled="loading"
        :aria-busy="loading"
        @click="refreshAnalytics"
      >
        <Icon name="rotate-ccw" />
        <span>{{ loading ? '刷新中' : '刷新数据' }}</span>
      </button>
    </div>

    <p v-if="loadError" class="provider-error" role="alert">{{ loadError }}</p>

    <section class="metrics analytics-metrics" aria-label="数据概览">
      <article v-for="tile in overviewTiles" :key="tile.label" class="metric analytics-metric">
        <div class="analytics-metric-head">
          <p class="metric-label">{{ tile.label }}</p>
          <Icon :name="tile.icon" />
        </div>
        <p class="metric-value">{{ tile.value }}</p>
        <span>{{ tile.caption }}</span>
      </article>
    </section>

    <section class="analytics-grid">
      <article class="panel analytics-panel analytics-wide">
        <div class="panel-head">
          <h2><Icon name="activity" /><span>每日 Agent run</span></h2>
          <span>{{ sourceName('agent_runs') }}</span>
        </div>
        <p v-if="cardError('daily_agent_runs')" class="analytics-error">
          {{ cardError('daily_agent_runs') }}
        </p>
        <div v-else-if="hasRows('daily_agent_runs')" class="analytics-line-scroll">
          <div class="analytics-line-chart">
            <div class="analytics-line-scale" aria-hidden="true">
              <span>{{ formatMetric(dailyAgentRunLine.maxValue, 'run_count') }}</span>
              <span>0</span>
            </div>
            <svg
              class="analytics-line-plot"
              :viewBox="`0 0 ${lineChartWidth} ${lineChartHeight}`"
              role="img"
              aria-label="每日 Agent run 折线图"
            >
              <line
                v-for="lineY in dailyAgentRunLine.gridLines"
                :key="lineY"
                :x1="lineChartPaddingX"
                :x2="lineChartWidth - lineChartPaddingX"
                :y1="lineY"
                :y2="lineY"
                class="analytics-line-grid"
              />
              <path :d="dailyAgentRunLine.areaPath" class="analytics-line-area" />
              <polyline :points="dailyAgentRunLine.polyline" class="analytics-line-series" />
              <circle
                v-for="point in dailyAgentRunLine.points"
                :key="point.label"
                :cx="point.x"
                :cy="point.y"
                r="5"
                class="analytics-line-point"
              >
                <title>{{ point.label }}：{{ point.value }}</title>
              </circle>
            </svg>
            <div
              class="analytics-line-labels"
              :style="{
                gridTemplateColumns: `repeat(${dailyAgentRunLine.points.length}, minmax(52px, 1fr))`,
              }"
            >
              <div v-for="point in dailyAgentRunLine.points" :key="point.label">
                <strong>{{ formatMetric(point.value, 'run_count') }}</strong>
                <small>{{ point.label }}</small>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="analytics-empty">暂无 Agent run 统计数据</div>
      </article>

      <article class="panel analytics-panel">
        <div class="panel-head">
          <h2><Icon name="database" /><span>Token 用量</span></h2>
        </div>
        <p v-if="cardError('token_usage')" class="analytics-error">
          {{ cardError('token_usage') }}
        </p>
        <div v-else class="analytics-ratio-list">
          <div>
            <span>输入 Token</span>
            <strong>{{ formatMetric(firstMetricValue('token_usage', 'prompt_tokens_total'), 'prompt_tokens_total') }}</strong>
          </div>
          <div>
            <span>缓存 Token</span>
            <strong>{{ formatMetric(firstMetricValue('token_usage', 'cached_prompt_tokens_total'), 'cached_prompt_tokens_total') }}</strong>
          </div>
          <div>
            <span>未缓存 Token</span>
            <strong>{{ formatMetric(firstMetricValue('token_usage', 'uncached_prompt_tokens_total'), 'uncached_prompt_tokens_total') }}</strong>
          </div>
          <div>
            <span>缓存命中率</span>
            <strong>{{ cacheHitRateLabel('token_usage') }}</strong>
          </div>
          <div>
            <span>缓存写入 Token</span>
            <strong>{{ formatMetric(firstMetricValue('token_usage', 'cache_write_prompt_tokens_total'), 'cache_write_prompt_tokens_total') }}</strong>
          </div>
          <div>
            <span>输出 Token</span>
            <strong>{{ formatMetric(firstMetricValue('token_usage', 'completion_tokens_total'), 'completion_tokens_total') }}</strong>
          </div>
          <div>
            <span>总 Token</span>
            <strong>{{ formatMetric(firstMetricValue('token_usage', 'total_tokens_total'), 'total_tokens_total') }}</strong>
          </div>
        </div>
      </article>

      <article class="panel analytics-panel">
        <div class="panel-head">
          <h2><Icon name="shield-check" /><span>运行结果占比</span></h2>
        </div>
        <p v-if="cardError('run_outcomes')" class="analytics-error">
          {{ cardError('run_outcomes') }}
        </p>
        <div v-else class="analytics-ratio-list">
          <div>
            <span>成功</span>
            <strong>{{ formatMetric(firstMetricValue('run_outcomes', 'successful_run_rate'), 'successful_run_rate') }}</strong>
          </div>
          <div>
            <span>失败</span>
            <strong>{{ formatMetric(firstMetricValue('run_outcomes', 'failed_run_rate'), 'failed_run_rate') }}</strong>
          </div>
          <div>
            <span>暂停</span>
            <strong>{{ formatMetric(firstMetricValue('run_outcomes', 'paused_run_rate'), 'paused_run_rate') }}</strong>
          </div>
        </div>
      </article>

      <article class="panel analytics-panel">
        <div class="panel-head">
          <h2><Icon name="message-square" /><span>每日新会话</span></h2>
        </div>
        <p v-if="cardError('daily_sessions')" class="analytics-error">
          {{ cardError('daily_sessions') }}
        </p>
        <div v-else-if="hasRows('daily_sessions')" class="analytics-mini-list">
          <div
            v-for="row in rows('daily_sessions')"
            :key="dimensionLabel(row, ['created_day'])"
          >
            <span>{{ dimensionLabel(row, ['created_day']) }}</span>
            <strong>{{ formatMetric(row.metrics?.session_count, 'session_count') }}</strong>
          </div>
        </div>
        <div v-else class="analytics-empty">暂无会话统计数据</div>
      </article>

      <article class="panel analytics-panel analytics-wide">
        <div class="panel-head">
          <h2><Icon name="table-2" /><span>Provider / Model 请求数</span></h2>
          <span>Top 8</span>
        </div>
        <p v-if="cardError('provider_model_requests')" class="analytics-error">
          {{ cardError('provider_model_requests') }}
        </p>
        <table v-else-if="hasRows('provider_model_requests')" class="analytics-table">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Model</th>
              <th>请求数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows('provider_model_requests')" :key="dimensionLabel(row, ['provider_id', 'model_id'])">
              <td>{{ row.dimensions?.provider_id || '未知' }}</td>
              <td>{{ row.dimensions?.model_id || '未知' }}</td>
              <td>{{ formatMetric(row.metrics?.run_count, 'run_count') }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="analytics-empty">暂无 provider/model 请求数据</div>
      </article>

      <article class="panel analytics-panel analytics-wide">
        <div class="panel-head">
          <h2><Icon name="table-2" /><span>Provider / Model Token 用量</span></h2>
          <span>Top 8</span>
        </div>
        <p v-if="cardError('provider_model_tokens')" class="analytics-error">
          {{ cardError('provider_model_tokens') }}
        </p>
        <div v-else-if="hasRows('provider_model_tokens')" class="analytics-table-scroll">
          <table class="analytics-table analytics-token-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model</th>
                <th>输入 Token</th>
                <th>缓存 Token</th>
                <th>命中率</th>
                <th>输出 Token</th>
                <th>总 Token</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows('provider_model_tokens')" :key="dimensionLabel(row, ['provider_id', 'model_id'])">
                <td>{{ row.dimensions?.provider_id || '未知' }}</td>
                <td>{{ row.dimensions?.model_id || '未知' }}</td>
                <td>{{ formatMetric(row.metrics?.prompt_tokens_total, 'prompt_tokens_total') }}</td>
                <td>{{ formatMetric(row.metrics?.cached_prompt_tokens_total, 'cached_prompt_tokens_total') }}</td>
                <td>{{ cacheHitRateLabel('provider_model_tokens', row) }}</td>
                <td>{{ formatMetric(row.metrics?.completion_tokens_total, 'completion_tokens_total') }}</td>
                <td>{{ formatMetric(row.metrics?.total_tokens_total, 'total_tokens_total') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="analytics-empty">暂无 provider/model Token 数据</div>
      </article>

      <article class="panel analytics-panel analytics-wide">
        <div class="panel-head">
          <h2><Icon name="wrench" /><span>工具调用统计</span></h2>
          <span>Top 8</span>
        </div>
        <p v-if="cardError('tool_calls_by_tool')" class="analytics-error">
          {{ cardError('tool_calls_by_tool') }}
        </p>
        <table v-else-if="hasRows('tool_calls_by_tool')" class="analytics-table">
          <thead>
            <tr>
              <th>工具</th>
              <th>调用</th>
              <th>成功</th>
              <th>失败</th>
              <th>需审批</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows('tool_calls_by_tool')" :key="dimensionLabel(row, ['tool_name'])">
              <td>{{ row.dimensions?.tool_name || '未知工具' }}</td>
              <td>{{ formatMetric(row.metrics?.tool_call_count, 'tool_call_count') }}</td>
              <td>{{ formatMetric(row.metrics?.tool_success_count, 'tool_success_count') }}</td>
              <td>{{ formatMetric(row.metrics?.tool_failure_count, 'tool_failure_count') }}</td>
              <td>{{ formatMetric(row.metrics?.tool_approval_required_count, 'tool_approval_required_count') }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="analytics-empty">暂无工具调用数据</div>
      </article>

      <article class="panel analytics-panel">
        <div class="panel-head">
          <h2><Icon name="database" /><span>上下文 / 记忆</span></h2>
        </div>
        <div class="analytics-ratio-list">
          <div>
            <span>平均上下文消息</span>
            <strong>{{ formatMetric(firstMetricValue('context_messages', 'average_message_count'), 'average_message_count') }}</strong>
          </div>
          <div>
            <span>有记忆写入的会话</span>
            <strong>{{ formatMetric(firstMetricValue('memory_write_sessions', 'sessions_with_memory_write_count'), 'sessions_with_memory_write_count') }}</strong>
          </div>
          <div>
            <span>平均工具轮次</span>
            <strong>{{ formatMetric(firstMetricValue('average_tool_rounds', 'average_tool_rounds'), 'average_tool_rounds') }}</strong>
          </div>
        </div>
      </article>

      <article class="panel analytics-panel">
        <div class="panel-head">
          <h2><Icon name="database" /><span>已注册数据源</span></h2>
          <span>{{ sources.length }} 个</span>
        </div>
        <div v-if="sources.length > 0" class="analytics-source-list">
          <div v-for="source in sources" :key="source.source_id">
            <strong>{{ source.name }}</strong>
            <span>{{ source.source_id }} · {{ source.metrics?.length || 0 }} metrics · {{ source.fields?.length || 0 }} fields</span>
          </div>
        </div>
        <div v-else class="analytics-empty">暂无已注册数据源</div>
      </article>
    </section>
  </section>
</template>
