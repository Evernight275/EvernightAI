import { requestJson } from './client'

export type DataFieldType = 'string' | 'integer' | 'number' | 'boolean' | 'datetime' | 'json'
export type DataAggregation = 'count' | 'sum' | 'average' | 'min' | 'max' | 'distinct_count' | 'rate' | 'custom'
export type DataFilterOperator =
  | 'equals'
  | 'not_equals'
  | 'greater_than'
  | 'greater_than_or_equals'
  | 'less_than'
  | 'less_than_or_equals'
  | 'in'
  | 'not_in'
  | 'contains'
  | 'between'
export type DataSortDirection = 'asc' | 'desc'
export type DataInsightKind =
  | 'summary'
  | 'trend'
  | 'anomaly'
  | 'comparison'
  | 'recommendation'

export type DataFieldDefinition = {
  field_id: string
  name: string
  field_type: DataFieldType
  description?: string | null
  metadata?: Record<string, unknown>
}

export type DataMetricDefinition = {
  metric_id: string
  name: string
  aggregation: DataAggregation
  field_id?: string | null
  description?: string | null
  unit?: string | null
  expression?: string | null
  metadata?: Record<string, unknown>
}

export type DataSourceDefinition = {
  source_id: string
  name: string
  description?: string | null
  fields?: DataFieldDefinition[]
  metrics?: DataMetricDefinition[]
  metadata?: Record<string, unknown>
}

export type DataFilter = {
  field_id: string
  operator: DataFilterOperator
  value: unknown
}

export type DataSort = {
  field_id: string
  direction?: DataSortDirection
}

export type DataTimeRange = {
  start?: string | null
  end?: string | null
  field_id?: string | null
}

export type DataStatisticsRequest = {
  source_id: string
  metrics: string[]
  dimensions?: string[]
  filters?: DataFilter[]
  time_range?: DataTimeRange | null
  sorts?: DataSort[]
  limit?: number | null
  metadata?: Record<string, unknown>
}

export type DataStatisticsRow = {
  dimensions?: Record<string, unknown>
  metrics?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export type DataStatisticsResult = {
  source_id: string
  rows?: DataStatisticsRow[]
  metadata?: Record<string, unknown>
}

export type DataAnalysisRequest = {
  source_id: string
  question?: string | null
  statistics_request?: DataStatisticsRequest | null
  metadata?: Record<string, unknown>
}

export type DataInsight = {
  kind: DataInsightKind
  title: string
  summary: string
  evidence?: DataStatisticsRow[]
  metadata?: Record<string, unknown>
}

export type DataAnalysisResult = {
  source_id: string
  statistics?: DataStatisticsResult | null
  insights?: DataInsight[]
  narrative?: string | null
  metadata?: Record<string, unknown>
}

export function listDataSources(signal?: AbortSignal): Promise<DataSourceDefinition[]> {
  return requestJson<DataSourceDefinition[]>('/data-analysis/sources', { signal })
}

export function getDataSource(sourceId: string): Promise<DataSourceDefinition> {
  return requestJson<DataSourceDefinition>(
    `/data-analysis/sources/${encodeURIComponent(sourceId)}`,
  )
}

export function listDataFields(sourceId: string): Promise<DataFieldDefinition[]> {
  return requestJson<DataFieldDefinition[]>(
    `/data-analysis/sources/${encodeURIComponent(sourceId)}/fields`,
  )
}

export function listDataMetrics(sourceId: string): Promise<DataMetricDefinition[]> {
  return requestJson<DataMetricDefinition[]>(
    `/data-analysis/sources/${encodeURIComponent(sourceId)}/metrics`,
  )
}

export function runDataStatistics(
  request: DataStatisticsRequest,
): Promise<DataStatisticsResult> {
  return requestJson<DataStatisticsResult>('/data-analysis/statistics', {
    method: 'POST',
    body: request,
  })
}

export function analyzeData(request: DataAnalysisRequest): Promise<DataAnalysisResult> {
  return requestJson<DataAnalysisResult>('/data-analysis/analyze', {
    method: 'POST',
    body: request,
  })
}
