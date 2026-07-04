import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from EvernightAI.core.domain.data_analysis import DataAnalysisManager, DataAnalysisRegister
from EvernightAI.core.error.data_analysis import (
    DataAnalysisInputError,
    DataStatisticsExecutionError,
)
from EvernightAI.core.schema.data_analysis import (
    DataAggregation,
    DataFieldDefinition,
    DataFieldType,
    DataFilter,
    DataFilterOperator,
    DataMetricDefinition,
    DataSort,
    DataSortDirection,
    DataSourceDefinition,
    DataTimeRange,
    DataStatisticsRequest,
)
from EvernightAI.infra.adapters.data_analysis.sqlite import (
    SQLiteDataStatisticsExecutor,
)
from EvernightAI.infra.registrations.data_analysis.sqlite import (
    register_sqlite_data_source,
)


def make_source() -> DataSourceDefinition:
    return DataSourceDefinition(
        source_id="orders",
        name="Orders",
        fields=[
            DataFieldDefinition(
                field_id="status",
                name="Status",
                field_type=DataFieldType.STRING,
            ),
            DataFieldDefinition(
                field_id="amount",
                name="Amount",
                field_type=DataFieldType.NUMBER,
            ),
            DataFieldDefinition(
                field_id="created_at",
                name="Created at",
                field_type=DataFieldType.DATETIME,
            ),
        ],
        metrics=[
            DataMetricDefinition(
                metric_id="order_count",
                name="Order count",
                aggregation=DataAggregation.COUNT,
            ),
            DataMetricDefinition(
                metric_id="revenue",
                name="Revenue",
                aggregation=DataAggregation.SUM,
                field_id="amount",
            ),
            DataMetricDefinition(
                metric_id="average_amount",
                name="Average amount",
                aggregation=DataAggregation.AVERAGE,
                field_id="amount",
            ),
            DataMetricDefinition(
                metric_id="minimum_amount",
                name="Minimum amount",
                aggregation=DataAggregation.MIN,
                field_id="amount",
            ),
            DataMetricDefinition(
                metric_id="maximum_amount",
                name="Maximum amount",
                aggregation=DataAggregation.MAX,
                field_id="amount",
            ),
            DataMetricDefinition(
                metric_id="status_count",
                name="Status count",
                aggregation=DataAggregation.COUNT,
                field_id="status",
            ),
            DataMetricDefinition(
                metric_id="distinct_status_count",
                name="Distinct status count",
                aggregation=DataAggregation.DISTINCT_COUNT,
                field_id="status",
            ),
        ],
        metadata={"sqlite_table": "orders"},
    )


def make_mapped_source() -> DataSourceDefinition:
    return DataSourceDefinition(
        source_id="mapped_orders",
        name="Mapped orders",
        fields=[
            DataFieldDefinition(
                field_id="public_status",
                name="Public status",
                field_type=DataFieldType.STRING,
                metadata={"sqlite_column": "status"},
            ),
            DataFieldDefinition(
                field_id="public_amount",
                name="Public amount",
                field_type=DataFieldType.NUMBER,
                metadata={"sqlite_column": "amount"},
            ),
        ],
        metrics=[
            DataMetricDefinition(
                metric_id="mapped_count",
                name="Mapped count",
                aggregation=DataAggregation.COUNT,
            ),
            DataMetricDefinition(
                metric_id="mapped_revenue",
                name="Mapped revenue",
                aggregation=DataAggregation.SUM,
                field_id="public_amount",
            ),
        ],
        metadata={"sqlite_view": "orders"},
    )


@pytest.mark.asyncio
async def test_sqlite_data_statistics_executor_aggregates_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    seed_orders(database_path)
    register = DataAnalysisRegister()
    register_sqlite_data_source(
        register,
        database_path=database_path,
        source=make_source(),
    )
    manager = DataAnalysisManager(register)

    result = await manager.statistics(
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count", "revenue"],
            dimensions=["status"],
            filters=[
                DataFilter(
                    field_id="created_at",
                    operator=DataFilterOperator.GREATER_THAN_OR_EQUALS,
                    value="2026-01-01T00:00:00",
                )
            ],
            sorts=[DataSort(field_id="revenue", direction=DataSortDirection.DESC)],
        )
    )

    assert result.rows[0].dimensions == {"status": "paid"}
    assert result.rows[0].metrics == {"order_count": 2, "revenue": 70.0}
    assert result.rows[1].dimensions == {"status": "refunded"}
    assert result.rows[1].metrics == {"order_count": 1, "revenue": 7.0}
    assert result.metadata == {
        "executor": "SQLiteDataStatisticsExecutor",
        "table": "orders",
    }


@pytest.mark.asyncio
async def test_sqlite_data_statistics_executor_rejects_unsafe_identifiers(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    seed_orders(database_path)
    register = DataAnalysisRegister()
    source = make_source().model_copy(
        update={"metadata": {"sqlite_table": "orders; drop table orders"}}
    )
    register_sqlite_data_source(
        register,
        database_path=database_path,
        source=source,
    )
    manager = DataAnalysisManager(register)

    with pytest.raises(DataAnalysisInputError):
        await manager.statistics(
            DataStatisticsRequest(
                source_id="orders",
                metrics=["order_count"],
            )
        )


@pytest.mark.asyncio
async def test_sqlite_data_statistics_executor_supports_filter_operators(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    seed_orders(database_path)
    manager = make_manager(database_path)

    paid_high_value = await manager.statistics(
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count", "revenue"],
            filters=[
                DataFilter(
                    field_id="status",
                    operator=DataFilterOperator.EQUALS,
                    value="paid",
                ),
                DataFilter(
                    field_id="amount",
                    operator=DataFilterOperator.GREATER_THAN,
                    value=35,
                ),
                DataFilter(
                    field_id="amount",
                    operator=DataFilterOperator.LESS_THAN_OR_EQUALS,
                    value=99,
                ),
            ],
        )
    )
    not_refunded = await manager.statistics(
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count", "minimum_amount", "maximum_amount"],
            filters=[
                DataFilter(
                    field_id="status",
                    operator=DataFilterOperator.NOT_EQUALS,
                    value="refunded",
                ),
                DataFilter(
                    field_id="amount",
                    operator=DataFilterOperator.GREATER_THAN_OR_EQUALS,
                    value=30,
                ),
                DataFilter(
                    field_id="amount",
                    operator=DataFilterOperator.LESS_THAN,
                    value=100,
                ),
            ],
        )
    )
    status_sets = await manager.statistics(
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count", "distinct_status_count"],
            filters=[
                DataFilter(
                    field_id="status",
                    operator=DataFilterOperator.CONTAINS,
                    value="aid",
                ),
                DataFilter(
                    field_id="status",
                    operator=DataFilterOperator.IN,
                    value=["paid", "refunded"],
                ),
                DataFilter(
                    field_id="status",
                    operator=DataFilterOperator.NOT_IN,
                    value=["refunded"],
                ),
                DataFilter(
                    field_id="amount",
                    operator=DataFilterOperator.BETWEEN,
                    value=[30, 99],
                ),
            ],
        )
    )

    assert paid_high_value.rows[0].metrics == {"order_count": 2, "revenue": 139.0}
    assert not_refunded.rows[0].metrics == {
        "order_count": 3,
        "minimum_amount": 30.0,
        "maximum_amount": 99.0,
    }
    assert status_sets.rows[0].metrics == {
        "order_count": 3,
        "distinct_status_count": 1,
    }


@pytest.mark.asyncio
async def test_sqlite_data_statistics_executor_applies_time_range_and_limit(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    seed_orders(database_path)
    manager = make_manager(database_path)

    result = await manager.statistics(
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count", "average_amount", "status_count"],
            dimensions=["status"],
            time_range=DataTimeRange(
                field_id="created_at",
                start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                end=datetime(2026, 1, 3, tzinfo=timezone.utc),
            ),
            sorts=[DataSort(field_id="average_amount", direction=DataSortDirection.DESC)],
            limit=1,
        )
    )

    assert len(result.rows) == 1
    assert result.rows[0].dimensions == {"status": "paid"}
    assert result.rows[0].metrics == {
        "order_count": 2,
        "average_amount": 35.0,
        "status_count": 2,
    }


@pytest.mark.asyncio
async def test_sqlite_data_statistics_executor_uses_view_and_column_metadata(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    seed_orders(database_path)
    register = DataAnalysisRegister()
    register_sqlite_data_source(
        register,
        database_path=database_path,
        source=make_mapped_source(),
    )
    manager = DataAnalysisManager(register)

    result = await manager.statistics(
        DataStatisticsRequest(
            source_id="mapped_orders",
            metrics=["mapped_count", "mapped_revenue"],
            dimensions=["public_status"],
            sorts=[DataSort(field_id="mapped_revenue", direction=DataSortDirection.DESC)],
        )
    )

    assert result.rows[0].dimensions == {"public_status": "paid"}
    assert result.rows[0].metrics == {"mapped_count": 3, "mapped_revenue": 169.0}
    assert result.metadata["table"] == "orders"


@pytest.mark.asyncio
async def test_sqlite_data_statistics_executor_rejects_invalid_metric_shapes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    seed_orders(database_path)

    fieldless_source = make_source().model_copy(
        update={
            "metrics": [
                DataMetricDefinition(
                    metric_id="bad_sum",
                    name="Bad sum",
                    aggregation=DataAggregation.SUM,
                )
            ]
        }
    )
    register = DataAnalysisRegister()
    register_sqlite_data_source(
        register,
        database_path=database_path,
        source=fieldless_source,
    )
    manager = DataAnalysisManager(register)

    with pytest.raises(DataAnalysisInputError, match="requires a field"):
        await manager.statistics(
            DataStatisticsRequest(source_id="orders", metrics=["bad_sum"])
        )

    unsupported_source = make_source().model_copy(
        update={
            "metrics": [
                DataMetricDefinition(
                    metric_id="bad_rate",
                    name="Bad rate",
                    aggregation=DataAggregation.RATE,
                    field_id="amount",
                )
            ]
        }
    )
    register = DataAnalysisRegister()
    register_sqlite_data_source(
        register,
        database_path=database_path,
        source=unsupported_source,
    )
    manager = DataAnalysisManager(register)

    with pytest.raises(DataAnalysisInputError, match="not supported"):
        await manager.statistics(
            DataStatisticsRequest(source_id="orders", metrics=["bad_rate"])
        )


@pytest.mark.asyncio
async def test_sqlite_data_statistics_executor_rejects_invalid_list_filters(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    seed_orders(database_path)
    manager = make_manager(database_path)

    with pytest.raises(DataAnalysisInputError, match="non-empty list"):
        await manager.statistics(
            DataStatisticsRequest(
                source_id="orders",
                metrics=["order_count"],
                filters=[
                    DataFilter(
                        field_id="status",
                        operator=DataFilterOperator.IN,
                        value=[],
                    )
                ],
            )
        )

    with pytest.raises(DataAnalysisInputError, match="two values"):
        await manager.statistics(
            DataStatisticsRequest(
                source_id="orders",
                metrics=["order_count"],
                filters=[
                    DataFilter(
                        field_id="amount",
                        operator=DataFilterOperator.BETWEEN,
                        value=[1, 2, 3],
                    )
                ],
            )
        )


@pytest.mark.asyncio
async def test_sqlite_data_statistics_executor_wraps_sqlite_errors(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    seed_orders(database_path)
    source = make_source()
    executor = SQLiteDataStatisticsExecutor(database_path, source)
    executor.close()

    with pytest.raises(DataStatisticsExecutionError) as exc_info:
        await executor.statistics(
            DataStatisticsRequest(source_id="orders", metrics=["order_count"])
        )

    assert "SQLite data source orders statistics failed" in str(exc_info.value)


def make_manager(database_path: Path) -> DataAnalysisManager:
    register = DataAnalysisRegister()
    register_sqlite_data_source(
        register,
        database_path=database_path,
        source=make_source(),
    )
    return DataAnalysisManager(register)


def seed_orders(database_path: Path) -> None:
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE orders (
            status TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO orders (status, amount, created_at) VALUES (?, ?, ?)",
        [
            ("paid", 30, "2026-01-02T00:00:00"),
            ("paid", 40, "2026-01-03T00:00:00"),
            ("refunded", 7, "2026-01-04T00:00:00"),
            ("paid", 99, "2025-12-31T00:00:00"),
        ],
    )
    connection.commit()
    connection.close()
