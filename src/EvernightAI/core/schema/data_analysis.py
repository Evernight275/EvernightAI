from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class DataFieldType(StrEnum):
    """数据字段类型"""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    JSON = "json"


class DataAggregation(StrEnum):
    """数据聚合方式"""

    COUNT = "count"
    SUM = "sum"
    AVERAGE = "average"
    MIN = "min"
    MAX = "max"
    DISTINCT_COUNT = "distinct_count"
    RATE = "rate"
    CUSTOM = "custom"


class DataFilterOperator(StrEnum):
    """数据筛选操作符"""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUALS = "greater_than_or_equals"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUALS = "less_than_or_equals"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    BETWEEN = "between"


class DataSortDirection(StrEnum):
    """数据排序方向"""

    ASC = "asc"
    DESC = "desc"


class DataInsightKind(StrEnum):
    """数据洞察类型"""

    SUMMARY = "summary"
    TREND = "trend"
    ANOMALY = "anomaly"
    COMPARISON = "comparison"
    RECOMMENDATION = "recommendation"


class DataFieldDefinition(EvernightAISchema):
    """数据字段定义"""

    field_id: str
    name: str
    field_type: DataFieldType
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataMetricDefinition(EvernightAISchema):
    """数据指标定义"""

    metric_id: str
    name: str
    aggregation: DataAggregation
    field_id: str | None = None
    description: str | None = None
    unit: str | None = None
    expression: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataSourceDefinition(EvernightAISchema):
    """数据源定义"""

    source_id: str
    name: str
    description: str | None = None
    fields: list[DataFieldDefinition] = Field(default_factory=list)
    metrics: list[DataMetricDefinition] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataTimeRange(EvernightAISchema):
    """数据时间范围"""

    start: datetime | None = None
    end: datetime | None = None
    field_id: str | None = None


class DataFilter(EvernightAISchema):
    """数据筛选条件"""

    field_id: str
    operator: DataFilterOperator
    value: Any


class DataSort(EvernightAISchema):
    """数据排序条件"""

    field_id: str
    direction: DataSortDirection = DataSortDirection.ASC


class DataStatisticsRequest(EvernightAISchema):
    """数据统计请求"""

    source_id: str
    metrics: list[str]
    dimensions: list[str] = Field(default_factory=list)
    filters: list[DataFilter] = Field(default_factory=list)
    time_range: DataTimeRange | None = None
    sorts: list[DataSort] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataStatisticsRow(EvernightAISchema):
    """数据统计行"""

    dimensions: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataStatisticsResult(EvernightAISchema):
    """数据统计结果"""

    source_id: str
    rows: list[DataStatisticsRow] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataAnalysisRequest(EvernightAISchema):
    """数据分析请求"""

    source_id: str
    question: str | None = None
    statistics_request: DataStatisticsRequest | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataInsight(EvernightAISchema):
    """数据洞察"""

    kind: DataInsightKind
    title: str
    summary: str
    evidence: list[DataStatisticsRow] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataAnalysisResult(EvernightAISchema):
    """数据分析结果"""

    source_id: str
    statistics: DataStatisticsResult | None = None
    insights: list[DataInsight] = Field(default_factory=list)
    narrative: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
