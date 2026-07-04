from typing import cast

import pytest

from EvernightAI.core.domain.data_analysis import (
    DataAnalysisManager,
    DataAnalysisRegister,
)
from EvernightAI.core.error.data_analysis import (
    DataAnalysisExecutionError,
    DataAnalysisInputError,
    DataAnalysisNotFoundError,
    DataAnalysisResultError,
    DataStatisticsExecutionError,
)
from EvernightAI.core.schema.data_analysis import (
    DataAggregation,
    DataAnalysisRequest,
    DataAnalysisResult,
    DataFieldDefinition,
    DataFieldType,
    DataInsight,
    DataInsightKind,
    DataFilter,
    DataFilterOperator,
    DataMetricDefinition,
    DataSort,
    DataSourceDefinition,
    DataStatisticsRequest,
    DataStatisticsResult,
    DataStatisticsRow,
    DataTimeRange,
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
    )


def make_statistics_result(source_id: str = "orders") -> DataStatisticsResult:
    return DataStatisticsResult(
        source_id=source_id,
        rows=[
            DataStatisticsRow(
                dimensions={"status": "paid"},
                metrics={"order_count": 2, "revenue": 42},
            )
        ],
    )


def make_statistics_request() -> DataStatisticsRequest:
    return DataStatisticsRequest(
        source_id="orders",
        metrics=["order_count", "revenue"],
        dimensions=["status"],
    )


class ClosableStatisticsExecutor:
    def __init__(self) -> None:
        self.close_count = 0

    async def statistics(
        self,
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    def close(self) -> None:
        self.close_count += 1


@pytest.mark.asyncio
async def test_data_analysis_manager_runs_registered_statistics() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        assert request.source_id == "orders"
        return make_statistics_result(request.source_id)

    register = DataAnalysisRegister()
    register.register(make_source(), statistics)
    manager = DataAnalysisManager(register)

    result = await manager.statistics(make_statistics_request())

    assert manager.list_sources() == [make_source()]
    assert [field.field_id for field in manager.list_fields("orders")] == [
        "status",
        "amount",
    ]
    assert [metric.metric_id for metric in manager.list_metrics("orders")] == [
        "order_count",
        "revenue",
    ]
    assert result.rows[0].metrics == {"order_count": 2, "revenue": 42}


@pytest.mark.asyncio
async def test_data_analysis_manager_uses_registered_analyzer() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    async def analyze(request: DataAnalysisRequest) -> DataAnalysisResult:
        assert request.question == "What changed?"
        return DataAnalysisResult(
            source_id=request.source_id,
            insights=[
                DataInsight(
                    kind=DataInsightKind.SUMMARY,
                    title="Revenue",
                    summary="Revenue is available.",
                )
            ],
            narrative="Revenue is available.",
        )

    register = DataAnalysisRegister()
    register.register(make_source(), statistics, analyze)
    manager = DataAnalysisManager(register)

    result = await manager.analyze(
        DataAnalysisRequest(source_id="orders", question="What changed?")
    )

    assert result.narrative == "Revenue is available."
    assert result.insights[0].kind is DataInsightKind.SUMMARY


@pytest.mark.asyncio
async def test_data_analysis_manager_falls_back_to_statistics_analysis() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    register = DataAnalysisRegister()
    register.register(make_source(), statistics)
    manager = DataAnalysisManager(register)

    result = await manager.analyze(
        DataAnalysisRequest(
            source_id="orders",
            statistics_request=make_statistics_request(),
        )
    )

    assert result.statistics == make_statistics_result()
    assert result.insights == []
    assert result.metadata["analyzer"] is None


def test_data_analysis_register_raises_for_missing_source() -> None:
    register = DataAnalysisRegister()

    with pytest.raises(DataAnalysisNotFoundError):
        register.get("missing")

    with pytest.raises(DataAnalysisNotFoundError):
        register.get_statistics_executor("missing")

    with pytest.raises(DataAnalysisNotFoundError):
        register.get_analyzer("missing")

    with pytest.raises(DataAnalysisNotFoundError):
        register.unregister("missing")


def test_data_analysis_register_unregisters_source() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    register = DataAnalysisRegister()
    register.register(make_source(), statistics)

    register.unregister("orders")

    assert register.has("orders") is False


def test_data_analysis_register_replaces_analyzer_and_closes_executor_once() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    async def analyze(request: DataAnalysisRequest) -> DataAnalysisResult:
        return DataAnalysisResult(source_id=request.source_id)

    register = DataAnalysisRegister()
    executor = ClosableStatisticsExecutor()

    register.register(make_source(), executor.statistics, analyze)
    assert register.get_analyzer("orders") is analyze

    register.register(make_source(), statistics)
    assert register.get_analyzer("orders") is None

    register.register(make_source(), executor.statistics)
    register.register(make_source().model_copy(update={"source_id": "orders-copy"}), executor.statistics)
    register.close()

    assert executor.close_count == 1


@pytest.mark.asyncio
async def test_data_analysis_manager_rejects_unknown_metric() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    register = DataAnalysisRegister()
    register.register(make_source(), statistics)
    manager = DataAnalysisManager(register)

    with pytest.raises(DataAnalysisInputError) as exc_info:
        await manager.statistics(
            DataStatisticsRequest(source_id="orders", metrics=["missing"])
        )

    assert exc_info.value.detail == "missing"


@pytest.mark.asyncio
async def test_data_analysis_manager_rejects_invalid_statistics_request_fields() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    register = DataAnalysisRegister()
    register.register(make_source(), statistics)
    manager = DataAnalysisManager(register)

    invalid_requests = [
        DataStatisticsRequest(source_id="orders", metrics=[]),
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count"],
            dimensions=["missing_dimension"],
        ),
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count"],
            filters=[
                DataFilter(
                    field_id="missing_filter",
                    operator=DataFilterOperator.EQUALS,
                    value="paid",
                )
            ],
        ),
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count"],
            sorts=[DataSort(field_id="missing_sort")],
        ),
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count"],
            time_range=DataTimeRange(field_id="missing_time"),
        ),
    ]

    for request in invalid_requests:
        with pytest.raises(DataAnalysisInputError):
            await manager.statistics(request)


@pytest.mark.asyncio
async def test_data_analysis_manager_allows_metric_sort_fields() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    register = DataAnalysisRegister()
    register.register(make_source(), statistics)
    manager = DataAnalysisManager(register)

    result = await manager.statistics(
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count"],
            sorts=[DataSort(field_id="order_count")],
        )
    )

    assert result.source_id == "orders"


@pytest.mark.asyncio
async def test_data_analysis_manager_wraps_statistics_errors() -> None:
    async def broken(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        raise RuntimeError("boom")

    register = DataAnalysisRegister()
    register.register(make_source(), broken)
    manager = DataAnalysisManager(register)

    with pytest.raises(DataStatisticsExecutionError) as exc_info:
        await manager.statistics(make_statistics_request())

    assert isinstance(exc_info.value.cause, RuntimeError)


@pytest.mark.asyncio
async def test_data_analysis_manager_preserves_statistics_errors() -> None:
    async def input_error(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        raise DataAnalysisInputError("bad input")

    async def execution_error(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        raise DataStatisticsExecutionError("bad execution")

    register = DataAnalysisRegister()
    register.register(make_source(), input_error)
    manager = DataAnalysisManager(register)

    with pytest.raises(DataAnalysisInputError, match="bad input"):
        await manager.statistics(make_statistics_request())

    register.register(make_source(), execution_error)

    with pytest.raises(DataStatisticsExecutionError, match="bad execution"):
        await manager.statistics(make_statistics_request())


@pytest.mark.asyncio
async def test_data_analysis_manager_wraps_analyzer_errors() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    async def broken(request: DataAnalysisRequest) -> DataAnalysisResult:
        raise RuntimeError("boom")

    register = DataAnalysisRegister()
    register.register(make_source(), statistics, broken)
    manager = DataAnalysisManager(register)

    with pytest.raises(DataAnalysisExecutionError) as exc_info:
        await manager.analyze(DataAnalysisRequest(source_id="orders"))

    assert isinstance(exc_info.value.cause, RuntimeError)


@pytest.mark.asyncio
async def test_data_analysis_manager_preserves_analysis_errors() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    async def broken(request: DataAnalysisRequest) -> DataAnalysisResult:
        raise DataAnalysisExecutionError("bad analysis")

    register = DataAnalysisRegister()
    register.register(make_source(), statistics, broken)
    manager = DataAnalysisManager(register)

    with pytest.raises(DataAnalysisExecutionError, match="bad analysis"):
        await manager.analyze(DataAnalysisRequest(source_id="orders"))


@pytest.mark.asyncio
async def test_data_analysis_manager_requires_statistics_request_without_analyzer() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    register = DataAnalysisRegister()
    register.register(make_source(), statistics)
    manager = DataAnalysisManager(register)

    with pytest.raises(DataAnalysisInputError):
        await manager.analyze(DataAnalysisRequest(source_id="orders"))


@pytest.mark.asyncio
async def test_data_analysis_manager_rejects_invalid_statistics_result() -> None:
    async def wrong_type(request: DataStatisticsRequest) -> DataStatisticsResult:
        return cast(DataStatisticsResult, object())

    async def wrong_source(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result("wrong-source")

    register = DataAnalysisRegister()
    register.register(make_source(), wrong_type)
    manager = DataAnalysisManager(register)

    with pytest.raises(DataAnalysisResultError, match="must be a DataStatisticsResult"):
        await manager.statistics(make_statistics_request())

    register.register(make_source(), wrong_source)

    with pytest.raises(DataAnalysisResultError, match="source must match"):
        await manager.statistics(make_statistics_request())


@pytest.mark.asyncio
async def test_data_analysis_manager_rejects_invalid_analysis_result() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return make_statistics_result(request.source_id)

    async def wrong_type(request: DataAnalysisRequest) -> DataAnalysisResult:
        return cast(DataAnalysisResult, object())

    async def wrong_source(request: DataAnalysisRequest) -> DataAnalysisResult:
        return DataAnalysisResult(source_id="wrong-source")

    register = DataAnalysisRegister()
    register.register(make_source(), statistics, wrong_type)
    manager = DataAnalysisManager(register)

    with pytest.raises(DataAnalysisResultError, match="must be a DataAnalysisResult"):
        await manager.analyze(DataAnalysisRequest(source_id="orders"))

    register.register(make_source(), statistics, wrong_source)

    with pytest.raises(DataAnalysisResultError, match="source must match"):
        await manager.analyze(DataAnalysisRequest(source_id="orders"))
