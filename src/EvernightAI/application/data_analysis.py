from EvernightAI.core.protocol.interface import DataAnalysisInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.data_analysis import (
    DataAnalysisRequest,
    DataAnalysisResult,
    DataFieldDefinition,
    DataMetricDefinition,
    DataSourceDefinition,
    DataStatisticsRequest,
    DataStatisticsResult,
)


class DataAnalysisApplication(DataAnalysisInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    def list_data_sources(self) -> list[DataSourceDefinition]:
        return self._runtime.data_analysis.list_sources()

    def get_data_source(self, source_id: str) -> DataSourceDefinition:
        return self._runtime.data_analysis.get_source(source_id)

    def list_data_fields(self, source_id: str) -> list[DataFieldDefinition]:
        return self._runtime.data_analysis.list_fields(source_id)

    def list_data_metrics(self, source_id: str) -> list[DataMetricDefinition]:
        return self._runtime.data_analysis.list_metrics(source_id)

    async def run_statistics(
        self,
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return await self._runtime.data_analysis.statistics(request)

    async def analyze_data(
        self,
        request: DataAnalysisRequest,
    ) -> DataAnalysisResult:
        return await self._runtime.data_analysis.analyze(request)
