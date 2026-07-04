from datetime import datetime
from pathlib import Path
from typing import Any
import re
import sqlite3

from EvernightAI.core.error.data_analysis import (
    DataAnalysisInputError,
    DataStatisticsExecutionError,
)
from EvernightAI.core.schema.data_analysis import (
    DataAggregation,
    DataFilter,
    DataFilterOperator,
    DataSortDirection,
    DataSourceDefinition,
    DataStatisticsRequest,
    DataStatisticsResult,
    DataStatisticsRow,
)


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SQLiteDataStatisticsExecutor:
    def __init__(
        self,
        database_path: str | Path,
        source: DataSourceDefinition,
        *,
        table_name: str | None = None,
    ) -> None:
        self._database_path = str(database_path)
        self._source = source
        self._table_name = table_name or _sqlite_table_name(source)
        self._field_columns = {
            field.field_id: _sqlite_column_name(field.field_id, field.metadata)
            for field in source.fields
        }
        if self._database_path != ":memory:":
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(self._database_path)
        self._connection.row_factory = sqlite3.Row

    async def statistics(
        self,
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        """执行 SQLite 数据统计"""
        query, parameters = self._build_query(request)
        try:
            cursor = self._connection.execute(query, parameters)
            rows = cursor.fetchall()
        except sqlite3.Error as exc:
            raise DataStatisticsExecutionError(
                f"The SQLite data source {self._source.source_id} statistics failed",
                detail=str(exc),
                cause=exc,
            ) from exc

        return DataStatisticsResult(
            source_id=request.source_id,
            rows=[
                DataStatisticsRow(
                    dimensions={
                        dimension: row[dimension]
                        for dimension in request.dimensions
                    },
                    metrics={
                        metric: row[metric]
                        for metric in request.metrics
                    },
                )
                for row in rows
            ],
            metadata={
                "executor": self.__class__.__name__,
                "table": self._table_name,
            },
        )

    def close(self) -> None:
        """关闭数据库连接"""
        self._connection.close()

    def _build_query(self, request: DataStatisticsRequest) -> tuple[str, list[Any]]:
        table = _quote_identifier(self._table_name)
        select_parts: list[str] = []
        group_parts: list[str] = []
        parameters: list[Any] = []

        for dimension in request.dimensions:
            column = _quote_identifier(self._field_columns[dimension])
            alias = _quote_identifier(dimension)
            select_parts.append(f"{column} AS {alias}")
            group_parts.append(column)

        for metric_id in request.metrics:
            metric_sql = self._metric_sql(metric_id)
            alias = _quote_identifier(metric_id)
            select_parts.append(f"{metric_sql} AS {alias}")

        where_parts = [
            self._filter_sql(filter_, parameters)
            for filter_ in request.filters
        ]
        if request.time_range is not None and request.time_range.field_id is not None:
            time_column = _quote_identifier(
                self._field_columns[request.time_range.field_id]
            )
            if request.time_range.start is not None:
                where_parts.append(f"{time_column} >= ?")
                parameters.append(_sqlite_value(request.time_range.start))
            if request.time_range.end is not None:
                where_parts.append(f"{time_column} <= ?")
                parameters.append(_sqlite_value(request.time_range.end))

        query_parts = [f"SELECT {', '.join(select_parts)} FROM {table}"]
        if where_parts:
            query_parts.append(f"WHERE {' AND '.join(where_parts)}")
        if group_parts:
            query_parts.append(f"GROUP BY {', '.join(group_parts)}")
        if request.sorts:
            query_parts.append(
                "ORDER BY "
                + ", ".join(
                    f"{_quote_identifier(sort.field_id)} {sort.direction.value.upper()}"
                    for sort in request.sorts
                )
            )
        if request.limit is not None:
            query_parts.append("LIMIT ?")
            parameters.append(request.limit)

        return " ".join(query_parts), parameters

    def _metric_sql(self, metric_id: str) -> str:
        metric = next(
            item for item in self._source.metrics if item.metric_id == metric_id
        )
        field = (
            _quote_identifier(self._field_columns[metric.field_id])
            if metric.field_id is not None
            else None
        )
        if metric.aggregation is DataAggregation.COUNT:
            return f"COUNT({field})" if field is not None else "COUNT(*)"
        if field is None:
            raise DataAnalysisInputError(
                f"The metric {metric.metric_id} requires a field"
            )
        if metric.aggregation is DataAggregation.SUM:
            return f"SUM({field})"
        if metric.aggregation is DataAggregation.AVERAGE:
            return f"AVG({field})"
        if metric.aggregation is DataAggregation.MIN:
            return f"MIN({field})"
        if metric.aggregation is DataAggregation.MAX:
            return f"MAX({field})"
        if metric.aggregation is DataAggregation.DISTINCT_COUNT:
            return f"COUNT(DISTINCT {field})"
        raise DataAnalysisInputError(
            f"The metric {metric.metric_id} aggregation is not supported by SQLite"
        )

    def _filter_sql(
        self,
        filter_: DataFilter,
        parameters: list[Any],
    ) -> str:
        column = _quote_identifier(self._field_columns[filter_.field_id])
        operator = filter_.operator
        value = filter_.value
        if operator is DataFilterOperator.EQUALS:
            parameters.append(_sqlite_value(value))
            return f"{column} = ?"
        if operator is DataFilterOperator.NOT_EQUALS:
            parameters.append(_sqlite_value(value))
            return f"{column} != ?"
        if operator is DataFilterOperator.GREATER_THAN:
            parameters.append(_sqlite_value(value))
            return f"{column} > ?"
        if operator is DataFilterOperator.GREATER_THAN_OR_EQUALS:
            parameters.append(_sqlite_value(value))
            return f"{column} >= ?"
        if operator is DataFilterOperator.LESS_THAN:
            parameters.append(_sqlite_value(value))
            return f"{column} < ?"
        if operator is DataFilterOperator.LESS_THAN_OR_EQUALS:
            parameters.append(_sqlite_value(value))
            return f"{column} <= ?"
        if operator is DataFilterOperator.CONTAINS:
            parameters.append(f"%{value}%")
            return f"{column} LIKE ?"
        if operator in {DataFilterOperator.IN, DataFilterOperator.NOT_IN}:
            values = _list_value(value, operator.value)
            parameters.extend(_sqlite_value(item) for item in values)
            placeholders = ", ".join("?" for _ in values)
            sql_operator = "IN" if operator is DataFilterOperator.IN else "NOT IN"
            return f"{column} {sql_operator} ({placeholders})"
        if operator is DataFilterOperator.BETWEEN:
            values = _list_value(value, operator.value)
            if len(values) != 2:
                raise DataAnalysisInputError("The between filter requires two values")
            parameters.extend(_sqlite_value(item) for item in values)
            return f"{column} BETWEEN ? AND ?"

        raise DataAnalysisInputError(f"Unsupported data filter operator: {operator}")


def _sqlite_table_name(source: DataSourceDefinition) -> str:
    table_name = source.metadata.get("sqlite_table") or source.metadata.get(
        "sqlite_view"
    )
    if isinstance(table_name, str) and table_name:
        return table_name

    return source.source_id


def _sqlite_column_name(field_id: str, metadata: dict[str, Any]) -> str:
    column_name = metadata.get("sqlite_column")
    if isinstance(column_name, str) and column_name:
        return column_name

    return field_id


def _quote_identifier(identifier: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise DataAnalysisInputError(
            "SQLite data analysis identifiers must contain only letters, "
            "numbers, and underscores",
            detail=identifier,
        )

    return f'"{identifier}"'


def _list_value(value: Any, operator: str) -> list[Any]:
    if isinstance(value, list) and value:
        return value

    raise DataAnalysisInputError(f"The {operator} filter requires a non-empty list")


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()

    return value
