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

export function listDataSources(): Promise<DataSourceDefinition[]> {
  return requestJson<DataSourceDefinition[]>('/data-analysis/sources')
}

export function runDataStatistics(
  request: DataStatisticsRequest,
): Promise<DataStatisticsResult> {
  return requestJson<DataStatisticsResult>('/data-analysis/statistics', {
    method: 'POST',
    body: request,
  })
}
