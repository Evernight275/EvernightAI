import sqlite3
from pathlib import Path

import pytest

from EvernightAI.core.domain.data_analysis import DataAnalysisManager, DataAnalysisRegister
from EvernightAI.core.error.data_analysis import DataAnalysisInputError
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
    DataStatisticsRequest,
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
        ],
        metadata={"sqlite_table": "orders"},
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
