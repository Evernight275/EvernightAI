<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listDataSources, getDataSource, listDataFields, listDataMetrics, runDataStatistics, analyzeData, type DataSourceDefinition, type DataFieldDefinition, type DataMetricDefinition, type DataStatisticsResult, type DataAnalysisResult } from '../../api'
const sources = ref<DataSourceDefinition[]>([])
const sourceId = ref('')
const source = ref<DataSourceDefinition | null>(null)
const fields = ref<DataFieldDefinition[]>([])
const metrics = ref<DataMetricDefinition[]>([])
const selectedMetrics = ref<string[]>([])
const dimension = ref('')
const question = ref('')
const limit = ref(20)
const statistics = ref<DataStatisticsResult | null>(null)
const analysis = ref<DataAnalysisResult | null>(null)
const busy = ref(false)
const error = ref('')
async function perform(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await action() } catch (cause) { error.value = cause instanceof Error ? cause.message : '查询失败' }
  finally { busy.value = false }
}
async function loadSource() {
  source.value = null; fields.value = []; metrics.value = []; selectedMetrics.value = []; dimension.value = ''; statistics.value = null; analysis.value = null
  if (!sourceId.value) return
  await perform(async () => {
    const id = sourceId.value
    const [definition, dataFields, dataMetrics] = await Promise.all([getDataSource(id), listDataFields(id), listDataMetrics(id)])
    source.value = definition; fields.value = dataFields; metrics.value = dataMetrics
  })
}
async function query(analyze: boolean) {
  await perform(async () => {
    if (!Number.isInteger(limit.value) || limit.value < 1 || limit.value > 1000) throw new Error('结果条数应为 1 到 1000 的整数')
    const request = { source_id: sourceId.value, metrics: [...selectedMetrics.value], dimensions: dimension.value ? [dimension.value] : [], limit: limit.value }
    statistics.value = null; analysis.value = null
    if (analyze) { analysis.value = await analyzeData({ source_id: sourceId.value, question: question.value, statistics_request: request }); statistics.value = analysis.value.statistics || null }
    else statistics.value = await runDataStatistics(request)
  })
}
onMounted(() => perform(async () => { sources.value = await listDataSources() }))
</script>
<template>
  <section class="settings-manager" aria-label="数据分析">
    <p v-if="error" role="alert">{{ error }}</p><p v-if="busy" role="status">正在查询…</p>
    <form class="settings-form" @submit.prevent="query(false)">
      <fieldset :disabled="busy">
        <label>数据源<select v-model="sourceId" required @change="loadSource"><option value="">选择数据源</option><option v-for="item in sources" :key="item.source_id" :value="item.source_id">{{ item.name }}</option></select></label>
        <p v-if="source" class="settings-help">{{ source.description }}</p>
        <label v-for="metric in metrics" :key="metric.metric_id" class="settings-checkbox"><input v-model="selectedMetrics" type="checkbox" :value="metric.metric_id" />{{ metric.name }} · {{ metric.description }}</label>
        <label>分组字段<select v-model="dimension"><option value="">不分组</option><option v-for="field in fields" :key="field.field_id" :value="field.field_id">{{ field.name }}</option></select></label>
        <label>结果条数<input v-model.number="limit" type="number" min="1" max="1000" required /></label>
        <label>分析问题<input v-model="question" placeholder="例如：最近有哪些变化？" /></label>
        <div class="settings-inline-actions"><button :disabled="!source || !selectedMetrics.length">查询统计</button><button type="button" :disabled="!source || !selectedMetrics.length || !question.trim()" @click="query(true)">分析数据</button></div>
      </fieldset>
    </form>
    <div v-if="statistics" class="settings-result" aria-label="统计结果"><p v-if="!statistics.rows?.length">没有符合条件的数据。</p><table v-else><thead><tr><th>分组</th><th v-for="metric in Object.keys(statistics.rows[0]?.metrics || {})" :key="metric">{{ metric }}</th></tr></thead><tbody><tr v-for="(row, index) in statistics.rows" :key="index"><td>{{ Object.values(row.dimensions || {}).join(' / ') || '全部' }}</td><td v-for="metric in Object.keys(statistics.rows[0]?.metrics || {})" :key="metric">{{ row.metrics?.[metric] ?? '—' }}</td></tr></tbody></table></div>
    <section v-if="analysis" aria-label="分析结果"><p>{{ analysis.narrative }}</p><div v-for="(insight, index) in analysis.insights" :key="index" class="settings-row"><div><h3>{{ insight.title }}</h3><p>{{ insight.summary }}</p></div></div></section>
  </section>
</template>
