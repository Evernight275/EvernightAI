from pathlib import Path

from EvernightAI.core.protocol.data_analysis import DataAnalysisRegisterProtocol
from EvernightAI.core.schema.data_analysis import DataSourceDefinition
from EvernightAI.infra.adapters.data_analysis.sqlite import (
    SQLiteDataStatisticsExecutor,
)


def register_sqlite_data_source(
    register: DataAnalysisRegisterProtocol,
    *,
    database_path: str | Path,
    source: DataSourceDefinition,
    table_name: str | None = None,
) -> SQLiteDataStatisticsExecutor:
    executor = SQLiteDataStatisticsExecutor(
        database_path,
        source,
        table_name=table_name,
    )
    register.register(source, executor.statistics)
    return executor
