import pytest

from EvernightAI.core.protocol.data_analysis import DataAnalysisManageProtocol
from EvernightAI.core.schema.data_analysis import (
    DataAggregation,
    DataAnalysisRequest,
    DataAnalysisResult,
    DataFieldDefinition,
    DataFieldType,
    DataInsight,
    DataInsightKind,
    DataMetricDefinition,
    DataSourceDefinition,
    DataStatisticsRequest,
    DataStatisticsResult,
    DataStatisticsRow,
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


class FakeDataAnalysisManager(DataAnalysisManageProtocol):
    def __init__(self, source: DataSourceDefinition) -> None:
        self._source = source

    def list_sources(self) -> list[DataSourceDefinition]:
        return [self._source]

    def get_source(self, source_id: str) -> DataSourceDefinition:
        assert source_id == self._source.source_id
        return self._source

    def list_fields(self, source_id: str) -> list[DataFieldDefinition]:
        return self.get_source(source_id).fields

    def list_metrics(self, source_id: str) -> list[DataMetricDefinition]:
        return self.get_source(source_id).metrics

    async def statistics(
        self,
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return DataStatisticsResult(
            source_id=request.source_id,
            rows=[
                DataStatisticsRow(
                    dimensions={"status": "paid"},
                    metrics={"order_count": 2, "revenue": 42},
                )
            ],
        )

    async def analyze(self, request: DataAnalysisRequest) -> DataAnalysisResult:
        statistics = request.statistics_request
        result = None
        if statistics is not None:
            result = await self.statistics(statistics)

        return DataAnalysisResult(
            source_id=request.source_id,
            statistics=result,
            insights=[
                DataInsight(
                    kind=DataInsightKind.SUMMARY,
                    title="Paid orders",
                    summary="Paid orders generated revenue.",
                    evidence=result.rows if result is not None else [],
                )
            ],
            narrative="Paid orders generated revenue.",
        )


@pytest.mark.asyncio
async def test_data_analysis_manage_protocol_shape() -> None:
    manager: DataAnalysisManageProtocol = FakeDataAnalysisManager(make_source())

    statistics_request = DataStatisticsRequest(
        source_id="orders",
        metrics=["order_count", "revenue"],
        dimensions=["status"],
    )

    statistics = await manager.statistics(statistics_request)
    analysis = await manager.analyze(
        DataAnalysisRequest(
            source_id="orders",
            question="How much paid revenue did we have?",
            statistics_request=statistics_request,
        )
    )

    assert [source.source_id for source in manager.list_sources()] == ["orders"]
    assert [field.field_id for field in manager.list_fields("orders")] == [
        "status",
        "amount",
    ]
    assert [metric.metric_id for metric in manager.list_metrics("orders")] == [
        "order_count",
        "revenue",
    ]
    assert statistics.rows[0].metrics == {"order_count": 2, "revenue": 42}
    assert analysis.statistics == statistics
    assert analysis.insights[0].kind is DataInsightKind.SUMMARY
