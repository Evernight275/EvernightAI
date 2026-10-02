from collections.abc import Awaitable, Callable
from typing import Protocol

from EvernightAI.core.schema.data_analysis import (
    DataAnalysisRequest,
    DataAnalysisResult,
    DataFieldDefinition,
    DataMetricDefinition,
    DataSourceDefinition,
    DataStatisticsRequest,
    DataStatisticsResult,
)


DataStatisticsExecutorProtocol = Callable[
    [DataStatisticsRequest], Awaitable[DataStatisticsResult]
]
DataAnalyzerProtocol = Callable[[DataAnalysisRequest], Awaitable[DataAnalysisResult]]


class DataAnalysisManageProtocol(Protocol):
    """
    数据统计分析管理协议
    """

    def list_sources(self) -> list[DataSourceDefinition]: ...

    def get_source(self, source_id: str) -> DataSourceDefinition: ...

    def list_fields(self, source_id: str) -> list[DataFieldDefinition]: ...

    def list_metrics(self, source_id: str) -> list[DataMetricDefinition]: ...

    async def statistics(
        self,
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult: ...

    async def analyze(self, request: DataAnalysisRequest) -> DataAnalysisResult: ...


class DataAnalysisRegisterProtocol(Protocol):
    """
    数据统计分析注册协议
    """

    def register(
        self,
        source: DataSourceDefinition,
        statistics_executor: DataStatisticsExecutorProtocol,
        analyzer: DataAnalyzerProtocol | None = None,
    ) -> None: ...

    def unregister(self, source_id: str) -> None: ...

    def get(self, source_id: str) -> DataSourceDefinition: ...

    def has(self, source_id: str) -> bool: ...

    def get_statistics_executor(
        self,
        source_id: str,
    ) -> DataStatisticsExecutorProtocol: ...

    def get_analyzer(self, source_id: str) -> DataAnalyzerProtocol | None: ...

    def list_sources(self) -> list[DataSourceDefinition]: ...
