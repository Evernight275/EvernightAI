<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { AgentRunSocketStatus, AgentRunState } from '../api'
import AgentRunTraceDetail from '../components/AgentRunTraceDetail.vue'
import Icon from '../components/Icon.vue'
import { formatStatus, statusTone } from '../format'

const props = defineProps<{
  runs: AgentRunState[]
  socketStatus: AgentRunSocketStatus
}>()

const selectedRunId = defineModel<string | null>('selectedRunId', { required: true })

const emit = defineEmits<{
  pause: [run: AgentRunState]
  cancel: [run: AgentRunState]
  resume: [run: AgentRunState]
}>()

const runPageSizeOptions = [10, 25, 50]
const runPage = ref(1)
const runPageSize = ref(runPageSizeOptions[0])

const runPageCount = computed(() => (
  Math.max(1, Math.ceil(props.runs.length / runPageSize.value))
))
const runPageStart = computed(() => (
  props.runs.length === 0 ? 0 : (runPage.value - 1) * runPageSize.value + 1
))
const runPageEnd = computed(() => (
  Math.min(props.runs.length, runPage.value * runPageSize.value)
))
const pagedRuns = computed(() => {
  const start = (runPage.value - 1) * runPageSize.value
  return props.runs.slice(start, start + runPageSize.value)
})
const selectedRun = computed(() => (
  props.runs.find((run) => run.run_id === selectedRunId.value)
  || pagedRuns.value[0]
  || props.runs[0]
  || null
))
const runIds = computed(() => props.runs.map((run) => run.run_id))

function setRunPage(nextPage: number) {
  runPage.value = Math.min(Math.max(nextPage, 1), runPageCount.value)
}

function selectRun(run: AgentRunState) {
  selectedRunId.value = run.run_id
}

watch([runIds, runPageSize], () => {
  setRunPage(runPage.value)
  if (!selectedRunId.value || !props.runs.some((run) => run.run_id === selectedRunId.value)) {
    selectedRunId.value = props.runs[0]?.run_id || null
  }
}, { immediate: true })
</script>

<template>
  <section class="run-workbench" aria-label="运行队列">
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
      <div class="run-table-scroll">
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
              <td class="run-empty-cell" colspan="5">
                <div class="run-empty-state">
                  <Icon name="activity" class="run-empty-icon" />
                  <strong>暂无运行记录</strong>
                  <span>Agent 运行后将在此显示</span>
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
              <td><span class="tag" :class="statusTone(run.status)">{{ formatStatus(run.status) }}</span></td>
              <td>{{ run.tool_rounds_used ?? 0 }} / {{ run.request.max_tool_rounds ?? 0 }}</td>
              <td>{{ run.trace?.length ?? 0 }}</td>
            </tr>
          </tbody>
        </table>
      </div>
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
      :socket-status="socketStatus"
      @pause="emit('pause', $event)"
      @cancel="emit('cancel', $event)"
      @resume="emit('resume', $event)"
    />
  </section>
</template>

<style scoped>
.run-empty-cell {
  padding: 32px;
  text-align: center;
}

.run-empty-state {
  display: inline-grid;
  gap: 8px;
  place-items: center;
}

.run-empty-state strong {
  color: var(--ink);
}

.run-empty-state span {
  color: var(--muted);
  font-size: 13px;
}

.run-empty-icon {
  width: 32px;
  height: 32px;
  color: var(--muted);
}
</style>
