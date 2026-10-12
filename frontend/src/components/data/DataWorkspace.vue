<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue';
import { Menu, RefreshCw } from '@lucide/vue';
import { runDataStatistics, type DataStatisticsRow } from '../../api';
import { authGeneration } from '../../runtime/workspaceRuntime';
import DataSettings from '../settings/DataSettings.vue';
import DataBarList, { type DataBarItem } from './DataBarList.vue';
import DataColumnChart from './DataColumnChart.vue';
import DataRunTimeline from './DataRunTimeline.vue';
import DataTokenCost from './DataTokenCost.vue';
import {
  compactNumber,
  dailySeries,
  dashboardRanges,
  dashboardRequests,
  metric,
  percentText,
  ratio,
  runFailureItems,
  tokenCost,
  tokenCostsByModel,
  toolFailureItems,
  type DashboardQuery,
  type DashboardRange,
} from './dataDashboard';

const props = defineProps<{ active: boolean }>();
defineEmits<{ navigation: [] }>();

const range = ref<DashboardRange>('30');
const rows = shallowRef<Partial<Record<DashboardQuery, DataStatisticsRow[]>>>({});
const failures = ref<string[]>([]);
const busy = ref(false);
const loaded = ref(false);
const refreshes = ref(0);
let sequence = 0;

async function load(): Promise<void> {
  const current = ++sequence;
  busy.value = true;
  refreshes.value += 1;
  const requests = Object.entries(dashboardRequests(range.value)) as [
    DashboardQuery,
    ReturnType<typeof dashboardRequests>[DashboardQuery],
  ][];
  const results = await Promise.allSettled(
    requests.map(([, request]) => runDataStatistics(request)),
  );
  // A newer range, identity or refresh owns the view now.
  if (current !== sequence) return;
  const next: Partial<Record<DashboardQuery, DataStatisticsRow[]>> = {};
  const errors = new Set<string>();
  results.forEach((result, index) => {
    const [name] = requests[index]!;
    if (result.status === 'fulfilled') next[name] = result.value.rows || [];
    else errors.add(result.reason instanceof Error ? result.reason.message : '无法读取统计数据');
  });
  rows.value = next;
  failures.value = [...errors];
  busy.value = false;
  loaded.value = true;
}

watch(
  [() => props.active, range, authGeneration],
  ([active]) => {
    if (active) void load();
  },
  { immediate: true },
);

const runs = computed(() => rows.value.runs?.[0]);
const events = computed(() => rows.value.events?.[0]);
const tiles = computed(() => {
  const observed = metric(runs.value, 'cache_observed_prompt_tokens_total');
  const failed = metric(events.value, 'tool_failure_count');
  return [
    { label: '运行次数', value: compactNumber(metric(runs.value, 'run_count')) },
    {
      label: '成功率',
      value: percentText(metric(runs.value, 'successful_run_rate')),
      note: `失败 ${percentText(metric(runs.value, 'failed_run_rate'))}`,
    },
    {
      label: 'Token 用量',
      value: compactNumber(metric(runs.value, 'total_tokens_total')),
      note: `输入 ${compactNumber(metric(runs.value, 'prompt_tokens_total'))} · 输出 ${compactNumber(metric(runs.value, 'completion_tokens_total'))}`,
    },
    {
      label: '缓存读取占比',
      value: percentText(ratio(metric(runs.value, 'cached_prompt_tokens_total'), observed)),
      // Providers that report no cache usage are left out instead of counted as zero.
      note: observed
        ? `基于 ${compactNumber(observed)} 个有缓存统计的输入 Token`
        : '服务商未返回缓存统计',
    },
    {
      label: '工具调用',
      value: compactNumber(metric(events.value, 'tool_call_count')),
      note: `失败 ${compactNumber(failed)} · 需审批 ${compactNumber(metric(events.value, 'tool_approval_required_count'))}`,
    },
    { label: '活跃会话', value: compactNumber(metric(runs.value, 'distinct_session_count')) },
  ];
});
const runsByDay = computed(() => dailySeries(rows.value.runsByDay || [], 'run_count', range.value));
const tokensByDay = computed(() =>
  dailySeries(rows.value.runsByDay || [], 'total_tokens_total', range.value),
);
const models = computed<DataBarItem[]>(() =>
  (rows.value.runsByModel || [])
    .filter((row) => (metric(row, 'run_count') ?? 0) > 0)
    .map((row) => ({
      label: String(row.dimensions?.model_id || '未记录模型'),
      value: metric(row, 'run_count') ?? 0,
      note: `${compactNumber(metric(row, 'total_tokens_total'))} Token · 成功率 ${percentText(metric(row, 'successful_run_rate'))}`,
    })),
);
const tools = computed<DataBarItem[]>(() =>
  (rows.value.tools || [])
    .filter((row) => row.dimensions?.tool_name && (metric(row, 'tool_call_count') ?? 0) > 0)
    .slice(0, 10)
    .map((row) => {
      const failed = metric(row, 'tool_failure_count') ?? 0;
      return {
        label: String(row.dimensions?.tool_name),
        value: metric(row, 'tool_call_count') ?? 0,
        note: failed ? `失败 ${compactNumber(failed)} 次` : undefined,
      };
    }),
);
const runFailures = computed(() =>
  runFailureItems(rows.value.runFailures || [], rows.value.errors || []),
);
const toolFailures = computed(() => toolFailureItems(rows.value.errors || []));
const totalCost = computed(() => tokenCost(runs.value, '全部'));
const modelCosts = computed(() => tokenCostsByModel(rows.value.runsByModel || []));
</script>

<template>
  <section class="data-page" aria-label="数据分析">
    <header class="chat-view-header">
      <div class="chat-header-main">
        <button
          class="icon-button chat-navigation-toggle"
          type="button"
          aria-label="会话管理"
          title="会话管理"
          @click="$emit('navigation')"
        >
          <Menu :size="18" aria-hidden="true" />
        </button>
        <div class="chat-header-heading">
          <h1 class="chat-header-title">数据分析</h1>
        </div>
        <button
          class="icon-button"
          type="button"
          title="刷新数据"
          aria-label="刷新数据"
          :disabled="busy"
          @click="load"
        >
          <RefreshCw :size="18" aria-hidden="true" />
        </button>
      </div>
    </header>
    <div class="data-page-content">
      <div class="data-filters" role="group" aria-label="时间范围">
        <button
          v-for="option in dashboardRanges"
          :key="option.id"
          type="button"
          :aria-pressed="range === option.id"
          @click="range = option.id"
        >
          {{ option.label }}
        </button>
        <span class="data-status" role="status">{{ busy ? '正在读取…' : '' }}</span>
      </div>
      <p v-for="message in failures" :key="message" class="data-error" role="alert">
        {{ message }}
      </p>
      <template v-if="loaded">
        <dl class="data-tiles">
          <div v-for="tile in tiles" :key="tile.label" class="data-tile">
            <dt>{{ tile.label }}</dt>
            <dd>{{ tile.value }}</dd>
            <small v-if="tile.note">{{ tile.note }}</small>
          </div>
        </dl>
        <div class="data-grid">
          <DataColumnChart title="每日运行次数" unit="次" :series="runsByDay" />
          <DataColumnChart title="每日 Token 用量" unit="Token" :series="tokensByDay" />
          <DataBarList title="按模型" unit="运行次数" :items="models" />
          <DataBarList title="工具调用" unit="调用次数" :items="tools" />
          <DataBarList title="运行失败原因" unit="运行次数" :items="runFailures" />
          <DataBarList title="工具失败原因" unit="失败次数" :items="toolFailures" />
          <DataTokenCost class="data-wide" :total="totalCost" :models="modelCosts" />
          <DataRunTimeline v-if="active" class="data-wide" :refresh-key="refreshes" />
        </div>
      </template>
      <details class="data-custom">
        <summary>自定义查询</summary>
        <DataSettings :key="authGeneration" />
      </details>
    </div>
  </section>
</template>
