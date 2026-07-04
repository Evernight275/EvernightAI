from typing import Annotated

from fastapi import APIRouter, Body

from EvernightAI.core.schema.data_analysis import (
    DataAnalysisRequest,
    DataAnalysisResult,
    DataFieldDefinition,
    DataMetricDefinition,
    DataSourceDefinition,
    DataStatisticsRequest,
    DataStatisticsResult,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.template import (
    DATA_ANALYSIS_EXAMPLES,
    DATA_STATISTICS_EXAMPLES,
)


router = APIRouter(prefix="/data-analysis", tags=["data-analysis"])


@router.get(
    "/sources",
    response_model=list[DataSourceDefinition],
    response_model_exclude_none=True,
    summary="List data sources",
    operation_id="list_data_sources",
)
async def list_data_sources(
    interface: InterfaceDependency,
) -> list[DataSourceDefinition]:
    return interface.data_analysis.list_data_sources()


@router.get(
    "/sources/{source_id}",
    response_model=DataSourceDefinition,
    response_model_exclude_none=True,
    summary="Get a data source",
    operation_id="get_data_source",
)
async def get_data_source(
    source_id: str,
    interface: InterfaceDependency,
) -> DataSourceDefinition:
    return interface.data_analysis.get_data_source(source_id)


@router.get(
    "/sources/{source_id}/fields",
    response_model=list[DataFieldDefinition],
    response_model_exclude_none=True,
    summary="List data source fields",
    operation_id="list_data_fields",
)
async def list_data_fields(
    source_id: str,
    interface: InterfaceDependency,
) -> list[DataFieldDefinition]:
    return interface.data_analysis.list_data_fields(source_id)


@router.get(
    "/sources/{source_id}/metrics",
    response_model=list[DataMetricDefinition],
    response_model_exclude_none=True,
    summary="List data source metrics",
    operation_id="list_data_metrics",
)
async def list_data_metrics(
    source_id: str,
    interface: InterfaceDependency,
) -> list[DataMetricDefinition]:
    return interface.data_analysis.list_data_metrics(source_id)


@router.post(
    "/statistics",
    response_model=DataStatisticsResult,
    response_model_exclude_none=True,
    summary="Run data statistics",
    operation_id="run_data_statistics",
)
async def run_data_statistics(
    request: Annotated[
        DataStatisticsRequest,
        Body(openapi_examples=DATA_STATISTICS_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> DataStatisticsResult:
    return await interface.data_analysis.run_statistics(request)


@router.post(
    "/analyze",
    response_model=DataAnalysisResult,
    response_model_exclude_none=True,
    summary="Analyze data",
    operation_id="analyze_data",
)
async def analyze_data(
    request: Annotated[
        DataAnalysisRequest,
        Body(openapi_examples=DATA_ANALYSIS_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> DataAnalysisResult:
    return await interface.data_analysis.analyze_data(request)
