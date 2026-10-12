<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue';
import {
  getAgentRun,
  listAgentRuns,
  listAgentTrace,
  type AgentRunState,
  type AgentTraceEvent,
} from '../../api';
import ChatToolTimeline from '../chat/ChatToolTimeline.vue';
import { toolElapsed } from '../chat/toolTiming';
import { compactNumber } from './dataDashboard';
import { runTimeShare, runTimelineEntries } from './runTimeline';

const props = defineProps<{ refreshKey: number }>();

const statusLabels: Record<string, string> = {
  running: '运行中',
  paused: '已暂停',
  canceled: '已取消',
  finished: '完成',
  failed: '失败',
};
const runs = shallowRef<AgentRunState[]>([]);
const selected = ref('');
const run = shallowRef<AgentRunState | null>(null);
const trace = shallowRef<AgentTraceEvent[]>([]);
const busy = ref(false);
const error = ref('');
let sequence = 0;

const startedAt = (item: AgentRunState): number => Date.parse(item.history?.started_at ?? '') || 0;
function optionLabel(item: AgentRunState): string {
  const time = startedAt(item)
    ? new Date(startedAt(item)).toLocaleString('zh-CN', { hour12: false })
    : '时间未知';
  const status = statusLabels[String(item.status)] ?? String(item.status ?? '未知');
  return `${time} · ${item.request.model_id} · ${status}`;
}

async function loadRuns(): Promise<void> {
  const current = ++sequence;
  busy.value = true;
  error.value = '';
  try {
    const loaded = await listAgentRuns();
    if (current !== sequence) return;
    runs.value = [...(Array.isArray(loaded) ? loaded : [])]
      .sort((a, b) => startedAt(b) - startedAt(a))
      .slice(0, 50);
    if (!runs.value.some((item) => item.run_id === selected.value))
      selected.value = runs.value[0]?.run_id ?? '';
    await loadRun(current);
  } catch (cause) {
    if (current !== sequence) return;
    error.value = cause instanceof Error ? cause.message : '无法读取运行记录';
    busy.value = false;
  }
}

async function loadRun(current = ++sequence): Promise<void> {
  if (!selected.value) {
    run.value = null;
    trace.value = [];
    busy.value = false;
    return;
  }
  busy.value = true;
  error.value = '';
  try {
    const [state, events] = await Promise.all([
      getAgentRun(selected.value),
      listAgentTrace(selected.value),
    ]);
    if (current !== sequence) return;
    run.value = state;
    // A malformed trace draws no timeline instead of breaking the page.
    trace.value = Array.isArray(events) ? events : [];
  } catch (cause) {
    if (current !== sequence) return;
    run.value = null;
    trace.value = [];
    error.value = cause instanceof Error ? cause.message : '无法读取执行轨迹';
  }
  busy.value = false;
}

watch(() => props.refreshKey, loadRuns, { immediate: true });

const entries = computed(() => runTimelineEntries(trace.value));
const facts = computed(() => {
  const share = runTimeShare(entries.value);
  const usage = run.value?.usage;
  const elapsed = (ms: number): string => toolElapsed({ durationMs: ms }) ?? '—';
  return [
    { label: '模型响应', value: elapsed(share.model) },
    { label: '工具执行', value: elapsed(share.tool) },
    { label: '等待审批', value: elapsed(share.wait) },
    {
      label: 'Token',
      value: compactNumber(usage?.total_tokens ?? undefined),
      note: usage
        ? `输入 ${compactNumber(usage.prompt_tokens ?? undefined)} · 输出 ${compactNumber(usage.completion_tokens ?? undefined)}`
        : undefined,
    },
  ];
});
</script>

<template>
  <figure class="data-chart data-run-timeline">
    <figcaption>
      <strong>单次运行执行轨迹</strong>
      <span role="status">{{ busy ? '正在读取…' : '' }}</span>
    </figcaption>
    <p v-if="error" class="data-error" role="alert">{{ error }}</p>
    <p v-if="!runs.length && !busy && !error" class="data-empty">还没有运行记录。</p>
    <template v-if="runs.length">
      <label class="data-run-picker">
        <span>选择运行</span>
        <select v-model="selected" :disabled="busy" @change="loadRun()">
          <option v-for="item in runs" :key="item.run_id" :value="item.run_id">
            {{ optionLabel(item) }}
          </option>
        </select>
      </label>
      <template v-if="run">
        <p v-if="run.failure" class="data-run-failure">
          失败原因：<strong>{{ run.failure.error_type }}</strong> {{ run.failure.message }}
        </p>
        <dl class="data-run-facts">
          <div v-for="fact in facts" :key="fact.label">
            <dt>{{ fact.label }}</dt>
            <dd>{{ fact.value }}</dd>
            <small v-if="fact.note">{{ fact.note }}</small>
          </div>
        </dl>
        <ChatToolTimeline :activities="entries" title="时间线" />
        <p v-if="entries.length < 2" class="data-empty">这次运行没有足够的计时事件来绘制时间线。</p>
      </template>
    </template>
  </figure>
</template>
