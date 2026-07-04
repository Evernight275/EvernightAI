from EvernightAI.core.error.data_analysis import (
    DataAnalysisExecutionError,
    DataAnalysisInputError,
    DataAnalysisNotFoundError,
    DataAnalysisResultError,
    DataStatisticsExecutionError,
)
from EvernightAI.core.protocol.data_analysis import (
    DataAnalysisManageProtocol,
    DataAnalysisRegisterProtocol,
    DataAnalyzerProtocol,
    DataStatisticsExecutorProtocol,
)
from EvernightAI.core.schema.data_analysis import (
    DataAnalysisRequest,
    DataAnalysisResult,
    DataFieldDefinition,
    DataMetricDefinition,
    DataSourceDefinition,
    DataStatisticsRequest,
    DataStatisticsResult,
)


def _callable_owner(callable_: object) -> object | None:
    owner = getattr(callable_, "__self__", None)
    return owner if owner is not None else None


class DataAnalysisRegister(DataAnalysisRegisterProtocol):
    def __init__(self) -> None:
        self._sources: dict[str, DataSourceDefinition] = {}
        self._statistics_executors: dict[str, DataStatisticsExecutorProtocol] = {}
        self._analyzers: dict[str, DataAnalyzerProtocol] = {}

    def register(
        self,
        source: DataSourceDefinition,
        statistics_executor: DataStatisticsExecutorProtocol,
        analyzer: DataAnalyzerProtocol | None = None,
    ) -> None:
        """注册数据源"""
        self._sources[source.source_id] = source
        self._statistics_executors[source.source_id] = statistics_executor
        if analyzer is not None:
            self._analyzers[source.source_id] = analyzer
        else:
            self._analyzers.pop(source.source_id, None)

    def unregister(self, source_id: str) -> None:
        """注销数据源"""
        if not self.has(source_id):
            raise DataAnalysisNotFoundError(
                f"The data source {source_id} is not registered"
            )

        self._sources.pop(source_id, None)
        self._statistics_executors.pop(source_id, None)
        self._analyzers.pop(source_id, None)

    def get(self, source_id: str) -> DataSourceDefinition:
        """获取数据源定义"""
        if self.has(source_id):
            return self._sources[source_id]
        raise DataAnalysisNotFoundError(f"The data source {source_id} is not found")

    def has(self, source_id: str) -> bool:
        """检查数据源是否存在"""
        return source_id in self._sources and source_id in self._statistics_executors

    def get_statistics_executor(
        self,
        source_id: str,
    ) -> DataStatisticsExecutorProtocol:
        """获取数据统计执行器"""
        if self.has(source_id):
            return self._statistics_executors[source_id]
        raise DataAnalysisNotFoundError(
            f"The data source {source_id} is not registered"
        )

    def get_analyzer(self, source_id: str) -> DataAnalyzerProtocol | None:
        """获取数据分析器"""
        if self.has(source_id):
            return self._analyzers.get(source_id)
        raise DataAnalysisNotFoundError(
            f"The data source {source_id} is not registered"
        )

    def list_sources(self) -> list[DataSourceDefinition]:
        """列出所有数据源定义"""
        return list(self._sources.values())

    def close(self) -> None:
        """关闭注册执行器持有的资源"""
        closed: set[int] = set()
        for executor in self._statistics_executors.values():
            owner = _callable_owner(executor)
            if owner is None or id(owner) in closed:
                continue
            close = getattr(owner, "close", None)
            if callable(close):
                close()
                closed.add(id(owner))


class DataAnalysisManager(DataAnalysisManageProtocol):
    def __init__(self, register: DataAnalysisRegisterProtocol) -> None:
        self._register = register

    def list_sources(self) -> list[DataSourceDefinition]:
        """列出所有数据源定义"""
        return self._register.list_sources()

    def get_source(self, source_id: str) -> DataSourceDefinition:
        """获取数据源定义"""
        return self._register.get(source_id)

    def list_fields(self, source_id: str) -> list[DataFieldDefinition]:
        """列出数据源字段"""
        return self._register.get(source_id).fields

    def list_metrics(self, source_id: str) -> list[DataMetricDefinition]:
        """列出数据源指标"""
        return self._register.get(source_id).metrics

    async def statistics(
        self,
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        """执行数据统计"""
        source = self._validate_statistics_request(request)
        executor = self._register.get_statistics_executor(source.source_id)

        try:
            result = await executor(request)
        except DataAnalysisInputError:
            raise
        except DataStatisticsExecutionError:
            raise
        except Exception as exc:
            raise DataStatisticsExecutionError(
                f"The data source {source.source_id} statistics failed",
                cause=exc,
            ) from exc

        self._validate_statistics_result(request, result)
        return result

    async def analyze(self, request: DataAnalysisRequest) -> DataAnalysisResult:
        """执行数据分析"""
        source = self._register.get(request.source_id)
        analyzer = self._register.get_analyzer(source.source_id)
        if analyzer is not None:
            try:
                result = await analyzer(request)
            except DataAnalysisExecutionError:
                raise
            except Exception as exc:
                raise DataAnalysisExecutionError(
                    f"The data source {source.source_id} analysis failed",
                    cause=exc,
                ) from exc

            self._validate_analysis_result(request, result)
            return result

        if request.statistics_request is None:
            raise DataAnalysisInputError(
                "The data analysis request must include a statistics request "
                "when no analyzer is registered"
            )

        statistics = await self.statistics(request.statistics_request)
        return DataAnalysisResult(
            source_id=source.source_id,
            statistics=statistics,
            metadata={
                "manager": self.__class__.__name__,
                "analyzer": None,
            },
        )

    def _validate_statistics_request(
        self,
        request: DataStatisticsRequest,
    ) -> DataSourceDefinition:
        source = self._register.get(request.source_id)
        if not request.metrics:
            raise DataAnalysisInputError(
                "The data statistics request must include at least one metric"
            )

        fields = {field.field_id for field in source.fields}
        metrics = {metric.metric_id for metric in source.metrics}
        unknown_metrics = sorted(set(request.metrics) - metrics)
        if unknown_metrics:
            raise DataAnalysisInputError(
                "The data statistics request includes unknown metrics",
                detail=", ".join(unknown_metrics),
            )

        unknown_dimensions = sorted(set(request.dimensions) - fields)
        if unknown_dimensions:
            raise DataAnalysisInputError(
                "The data statistics request includes unknown dimensions",
                detail=", ".join(unknown_dimensions),
            )

        filter_fields = {filter_.field_id for filter_ in request.filters}
        unknown_filters = sorted(filter_fields - fields)
        if unknown_filters:
            raise DataAnalysisInputError(
                "The data statistics request includes unknown filter fields",
                detail=", ".join(unknown_filters),
            )

        sort_targets = {sort.field_id for sort in request.sorts}
        unknown_sorts = sorted(sort_targets - fields - metrics)
        if unknown_sorts:
            raise DataAnalysisInputError(
                "The data statistics request includes unknown sort fields",
                detail=", ".join(unknown_sorts),
            )

        if (
            request.time_range is not None
            and request.time_range.field_id is not None
            and request.time_range.field_id not in fields
        ):
            raise DataAnalysisInputError(
                "The data statistics request includes an unknown time range field",
                detail=request.time_range.field_id,
            )

        return source

    def _validate_statistics_result(
        self,
        request: DataStatisticsRequest,
        result: object,
    ) -> None:
        if not isinstance(result, DataStatisticsResult):
            raise DataAnalysisResultError(
                "The data statistics result must be a DataStatisticsResult"
            )
        if result.source_id != request.source_id:
            raise DataAnalysisResultError(
                "The data statistics result source must match the request source"
            )

    def _validate_analysis_result(
        self,
        request: DataAnalysisRequest,
        result: object,
    ) -> None:
        if not isinstance(result, DataAnalysisResult):
            raise DataAnalysisResultError(
                "The data analysis result must be a DataAnalysisResult"
            )
        if result.source_id != request.source_id:
            raise DataAnalysisResultError(
                "The data analysis result source must match the request source"
            )
