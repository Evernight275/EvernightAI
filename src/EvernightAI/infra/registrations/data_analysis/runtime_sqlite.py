from pathlib import Path
import sqlite3

from EvernightAI.core.protocol.data_analysis import DataAnalysisRegisterProtocol
from EvernightAI.core.schema.data_analysis import (
    DataAggregation,
    DataFieldDefinition,
    DataFieldType,
    DataMetricDefinition,
    DataSourceDefinition,
)
from EvernightAI.infra.registrations.data_analysis.sqlite import (
    register_sqlite_data_source,
)


def register_sqlite_runtime_data_analysis_sources(
    register: DataAnalysisRegisterProtocol,
    *,
    database_path: str | Path,
    include_agent_sources: bool = True,
) -> None:
    ensure_sqlite_runtime_data_analysis_views(
        database_path,
        include_agent_sources=include_agent_sources,
    )
    for source in sqlite_runtime_data_analysis_sources(
        include_agent_sources=include_agent_sources,
    ):
        register_sqlite_data_source(
            register,
            database_path=database_path,
            source=source,
        )


def ensure_sqlite_runtime_data_analysis_views(
    database_path: str | Path,
    *,
    include_agent_sources: bool = True,
) -> None:
    connection = sqlite3.connect(database_path)
    try:
        if include_agent_sources:
            _replace_sqlite_view(
                connection,
                "evernight_agent_runs",
                AGENT_RUNS_VIEW_SQL,
            )
            _replace_sqlite_view(
                connection,
                "evernight_agent_trace_events",
                AGENT_TRACE_EVENTS_VIEW_SQL,
            )
        _replace_sqlite_view(connection, "evernight_sessions", SESSIONS_VIEW_SQL)
        _replace_sqlite_view(connection, "evernight_contexts", CONTEXTS_VIEW_SQL)
        _replace_sqlite_view(connection, "evernight_memories", MEMORIES_VIEW_SQL)
        connection.commit()
    finally:
        connection.close()


def sqlite_runtime_data_analysis_sources(
    *,
    include_agent_sources: bool = True,
) -> list[DataSourceDefinition]:
    sources = [
        _sessions_source(),
        _contexts_source(),
        _memories_source(),
    ]
    if include_agent_sources:
        sources = [
            _agent_runs_source(),
            _agent_trace_events_source(),
            *sources,
        ]

    return sources


AGENT_RUNS_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS evernight_agent_runs AS
WITH chat_usage AS (
    SELECT
        run.run_id,
        COUNT(*) AS chat_call_count,
        SUM(json_extract(step.value, '$.response.usage.prompt_tokens'))
            AS prompt_tokens,
        SUM(json_extract(step.value, '$.response.usage.completion_tokens'))
            AS completion_tokens,
        SUM(
            COALESCE(
                json_extract(step.value, '$.response.usage.total_tokens'),
                COALESCE(
                    json_extract(step.value, '$.response.usage.prompt_tokens'),
                    0
                ) + COALESCE(
                    json_extract(step.value, '$.response.usage.completion_tokens'),
                    0
                )
            )
        ) AS total_tokens,
        SUM(
            COALESCE(
                json_extract(
                    step.value,
                    '$.response.usage.cached_prompt_tokens'
                ),
                json_extract(
                    step.value,
                    '$.response.usage.metadata.prompt_tokens_details.cached_tokens'
                ),
                json_extract(
                    step.value,
                    '$.response.usage.metadata.input_tokens_details.cached_tokens'
                ),
                json_extract(
                    step.value,
                    '$.response.usage.metadata.cache_read_input_tokens'
                ),
                json_extract(
                    step.value,
                    '$.response.usage.metadata.cachedContentTokenCount'
                )
            )
        ) AS cached_prompt_tokens,
        SUM(
            COALESCE(
                json_extract(
                    step.value,
                    '$.response.usage.cached_prompt_tokens'
                ),
                json_extract(
                    step.value,
                    '$.response.usage.metadata.prompt_tokens_details.cached_tokens'
                ),
                json_extract(
                    step.value,
                    '$.response.usage.metadata.input_tokens_details.cached_tokens'
                ),
                json_extract(
                    step.value,
                    '$.response.usage.metadata.cache_read_input_tokens'
                ),
                json_extract(
                    step.value,
                    '$.response.usage.metadata.cachedContentTokenCount'
                )
            ) IS NOT NULL
        ) AS cache_read_report_count,
        SUM(
            COALESCE(
                json_extract(
                    step.value,
                    '$.response.usage.cache_write_prompt_tokens'
                ),
                json_extract(
                    step.value,
                    '$.response.usage.metadata.cache_creation_input_tokens'
                )
            )
        ) AS cache_write_prompt_tokens,
        SUM(
            COALESCE(
                json_extract(
                    step.value,
                    '$.response.usage.cache_write_prompt_tokens'
                ),
                json_extract(
                    step.value,
                    '$.response.usage.metadata.cache_creation_input_tokens'
                )
            ) IS NOT NULL
        ) AS cache_write_report_count
    FROM agent_run_states AS run
    JOIN json_each(json_extract(run.payload, '$.steps')) AS step
    WHERE json_extract(step.value, '$.step_type') = 'chat'
    GROUP BY run.run_id
),
run_usage AS (
    SELECT
        run.*,
        COALESCE(
            chat.prompt_tokens,
            json_extract(run.payload, '$.response.usage.prompt_tokens'),
            0
        ) AS normalized_prompt_tokens,
        COALESCE(
            chat.completion_tokens,
            json_extract(run.payload, '$.response.usage.completion_tokens'),
            0
        ) AS normalized_completion_tokens,
        COALESCE(
            chat.total_tokens,
            json_extract(run.payload, '$.response.usage.total_tokens'),
            COALESCE(
                json_extract(run.payload, '$.response.usage.prompt_tokens'),
                0
            ) + COALESCE(
                json_extract(run.payload, '$.response.usage.completion_tokens'),
                0
            ),
            0
        ) AS normalized_total_tokens,
        CASE
            WHEN chat.chat_call_count IS NOT NULL THEN
                CASE
                    WHEN chat.cache_read_report_count = chat.chat_call_count
                    THEN chat.cached_prompt_tokens
                    ELSE NULL
                END
            ELSE COALESCE(
                json_extract(
                    run.payload,
                    '$.response.usage.cached_prompt_tokens'
                ),
                json_extract(
                    run.payload,
                    '$.response.usage.metadata.prompt_tokens_details.cached_tokens'
                ),
                json_extract(
                    run.payload,
                    '$.response.usage.metadata.input_tokens_details.cached_tokens'
                ),
                json_extract(
                    run.payload,
                    '$.response.usage.metadata.cache_read_input_tokens'
                ),
                json_extract(
                    run.payload,
                    '$.response.usage.metadata.cachedContentTokenCount'
                )
            )
        END AS normalized_cached_prompt_tokens,
        CASE
            WHEN chat.chat_call_count IS NOT NULL THEN
                CASE
                    WHEN chat.cache_write_report_count = chat.chat_call_count
                    THEN chat.cache_write_prompt_tokens
                    ELSE NULL
                END
            ELSE COALESCE(
                json_extract(
                    run.payload,
                    '$.response.usage.cache_write_prompt_tokens'
                ),
                json_extract(
                    run.payload,
                    '$.response.usage.metadata.cache_creation_input_tokens'
                )
            )
        END AS normalized_cache_write_prompt_tokens
    FROM agent_run_states AS run
    LEFT JOIN chat_usage AS chat ON chat.run_id = run.run_id
)
SELECT
    run_id,
    json_extract(payload, '$.request.provider_id') AS provider_id,
    json_extract(payload, '$.request.model_id') AS model_id,
    json_extract(payload, '$.request.context_id') AS context_id,
    json_extract(payload, '$.request.metadata.session_id') AS session_id,
    json_extract(payload, '$.status') AS status,
    json_extract(payload, '$.stop_reason') AS stop_reason,
    COALESCE(json_extract(payload, '$.tool_rounds_used'), 0) AS tool_rounds_used,
    COALESCE(
        json_array_length(json_extract(payload, '$.pending_approval_requests')),
        0
    ) AS pending_approval_count,
    COALESCE(json_extract(payload, '$.request.max_tool_rounds'), 0) AS max_tool_rounds,
    COALESCE(json_extract(payload, '$.request.write_memory'), 0) AS write_memory,
    normalized_prompt_tokens AS prompt_tokens,
    normalized_completion_tokens AS completion_tokens,
    normalized_total_tokens AS total_tokens,
    normalized_cached_prompt_tokens AS cached_prompt_tokens,
    normalized_cache_write_prompt_tokens AS cache_write_prompt_tokens,
    CASE
        WHEN normalized_cached_prompt_tokens IS NOT NULL
        THEN normalized_prompt_tokens
        ELSE NULL
    END AS cache_observed_prompt_tokens,
    CASE
        WHEN normalized_cached_prompt_tokens IS NOT NULL
        THEN MAX(
            normalized_prompt_tokens - normalized_cached_prompt_tokens,
            0
        )
        ELSE NULL
    END AS uncached_prompt_tokens,
    CASE
        WHEN json_extract(payload, '$.status') = 'finished' THEN 1
        ELSE 0
    END AS is_successful,
    CASE
        WHEN json_extract(payload, '$.status') = 'failed' THEN 1
        ELSE 0
    END AS is_failed,
    CASE
        WHEN json_extract(payload, '$.status') = 'paused' THEN 1
        ELSE 0
    END AS is_paused,
    created_at,
    updated_at,
    substr(created_at, 1, 10) AS created_day,
    substr(updated_at, 1, 10) AS updated_day
FROM run_usage
"""


AGENT_TRACE_EVENTS_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS evernight_agent_trace_events AS
SELECT
    trace.event_id,
    trace.run_id,
    json_extract(trace.payload, '$.event_type') AS event_type,
    json_extract(trace.payload, '$.step_type') AS step_type,
    COALESCE(
        json_extract(trace.payload, '$.approval_request.tool_name'),
        json_extract(trace.payload, '$.tool_call.tool_call.tool_name'),
        json_extract(trace.payload, '$.tool_call.tool_call.name')
    ) AS tool_name,
    json_extract(trace.payload, '$.approval_decision.status') AS approval_status,
    json_extract(trace.payload, '$.error_type') AS error_type,
    json_extract(trace.payload, '$.metadata.memory_id') AS memory_id,
    CASE
        WHEN json_extract(trace.payload, '$.event_type') IN (
            'tool_completed',
            'tool_failed'
        ) THEN 1
        ELSE 0
    END AS is_tool_call,
    CASE
        WHEN json_extract(trace.payload, '$.event_type') = 'tool_completed' THEN 1
        ELSE 0
    END AS is_tool_success,
    CASE
        WHEN json_extract(trace.payload, '$.event_type') = 'tool_failed' THEN 1
        ELSE 0
    END AS is_tool_failure,
    CASE
        WHEN json_extract(trace.payload, '$.event_type') = 'tool_approval_requested'
        THEN 1
        ELSE 0
    END AS is_tool_approval_required,
    CASE
        WHEN json_extract(trace.payload, '$.event_type') = 'memory_written' THEN 1
        ELSE 0
    END AS is_memory_write,
    CASE
        WHEN json_extract(trace.payload, '$.event_type') = 'memory_written'
        THEN json_extract(state.payload, '$.request.metadata.session_id')
        ELSE NULL
    END AS memory_write_session_id,
    json_extract(state.payload, '$.request.provider_id') AS provider_id,
    json_extract(state.payload, '$.request.model_id') AS model_id,
    json_extract(state.payload, '$.request.context_id') AS context_id,
    json_extract(state.payload, '$.request.metadata.session_id') AS session_id,
    trace.created_at,
    substr(trace.created_at, 1, 10) AS event_day
FROM agent_trace_events AS trace
LEFT JOIN agent_run_states AS state
    ON state.run_id = trace.run_id
"""


SESSIONS_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS evernight_sessions AS
SELECT
    session_id,
    json_extract(payload, '$.title') AS title,
    json_extract(payload, '$.context_id') AS context_id,
    json_extract(payload, '$.provider_id') AS provider_id,
    json_extract(payload, '$.model_id') AS model_id,
    json_extract(payload, '$.status') AS status,
    json_extract(payload, '$.created_at') AS created_at,
    json_extract(payload, '$.updated_at') AS updated_at,
    substr(json_extract(payload, '$.created_at'), 1, 10) AS created_day,
    substr(json_extract(payload, '$.updated_at'), 1, 10) AS updated_day
FROM sessions
"""


CONTEXTS_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS evernight_contexts AS
SELECT
    context_id,
    COALESCE(json_array_length(json_extract(payload, '$.messages')), 0) AS message_count
FROM contexts
"""


MEMORIES_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS evernight_memories AS
SELECT
    memory_id,
    json_extract(payload, '$.kind') AS kind,
    json_extract(payload, '$.scope') AS scope,
    json_extract(payload, '$.scope_id') AS scope_id,
    COALESCE(json_extract(payload, '$.priority'), 0) AS priority,
    COALESCE(json_extract(payload, '$.is_enabled'), 1) AS is_enabled
FROM memories
"""


def _agent_runs_source() -> DataSourceDefinition:
    return DataSourceDefinition(
        source_id="agent_runs",
        name="Agent runs",
        description="Persisted agent run state snapshots.",
        fields=[
            _field("run_id", "Run ID", DataFieldType.STRING),
            _field("provider_id", "Provider ID", DataFieldType.STRING),
            _field("model_id", "Model ID", DataFieldType.STRING),
            _field("context_id", "Context ID", DataFieldType.STRING),
            _field("session_id", "Session ID", DataFieldType.STRING),
            _field("status", "Run status", DataFieldType.STRING),
            _field("stop_reason", "Stop reason", DataFieldType.STRING),
            _field("tool_rounds_used", "Tool rounds used", DataFieldType.INTEGER),
            _field("pending_approval_count", "Pending approval count", DataFieldType.INTEGER),
            _field("max_tool_rounds", "Max tool rounds", DataFieldType.INTEGER),
            _field("write_memory", "Write memory", DataFieldType.BOOLEAN),
            _field("prompt_tokens", "Prompt tokens", DataFieldType.INTEGER),
            _field("completion_tokens", "Completion tokens", DataFieldType.INTEGER),
            _field("total_tokens", "Total tokens", DataFieldType.INTEGER),
            _field("cached_prompt_tokens", "Cached prompt tokens", DataFieldType.INTEGER),
            _field("cache_write_prompt_tokens", "Cache write prompt tokens", DataFieldType.INTEGER),
            _field("cache_observed_prompt_tokens", "Cache-observed prompt tokens", DataFieldType.INTEGER),
            _field("uncached_prompt_tokens", "Uncached prompt tokens", DataFieldType.INTEGER),
            _field("is_successful", "Is successful", DataFieldType.BOOLEAN),
            _field("is_failed", "Is failed", DataFieldType.BOOLEAN),
            _field("is_paused", "Is paused", DataFieldType.BOOLEAN),
            _field("created_at", "Created at", DataFieldType.DATETIME),
            _field("updated_at", "Updated at", DataFieldType.DATETIME),
            _field("created_day", "Created day", DataFieldType.STRING),
            _field("updated_day", "Updated day", DataFieldType.STRING),
        ],
        metrics=[
            _metric("run_count", "Run count", DataAggregation.COUNT),
            _metric("tool_rounds_total", "Tool rounds total", DataAggregation.SUM, "tool_rounds_used"),
            _metric("average_tool_rounds", "Average tool rounds", DataAggregation.AVERAGE, "tool_rounds_used"),
            _metric("successful_run_rate", "Successful run rate", DataAggregation.AVERAGE, "is_successful"),
            _metric("failed_run_rate", "Failed run rate", DataAggregation.AVERAGE, "is_failed"),
            _metric("paused_run_rate", "Paused run rate", DataAggregation.AVERAGE, "is_paused"),
            _metric("pending_approvals_total", "Pending approvals total", DataAggregation.SUM, "pending_approval_count"),
            _metric("distinct_session_count", "Distinct session count", DataAggregation.DISTINCT_COUNT, "session_id"),
            _metric("prompt_tokens_total", "Prompt tokens total", DataAggregation.SUM, "prompt_tokens"),
            _metric("completion_tokens_total", "Completion tokens total", DataAggregation.SUM, "completion_tokens"),
            _metric("total_tokens_total", "Total tokens", DataAggregation.SUM, "total_tokens"),
            _metric("cached_prompt_tokens_total", "Cached prompt tokens", DataAggregation.SUM, "cached_prompt_tokens"),
            _metric("cache_write_prompt_tokens_total", "Cache write prompt tokens", DataAggregation.SUM, "cache_write_prompt_tokens"),
            _metric("cache_observed_prompt_tokens_total", "Cache-observed prompt tokens", DataAggregation.SUM, "cache_observed_prompt_tokens"),
            _metric("uncached_prompt_tokens_total", "Uncached prompt tokens", DataAggregation.SUM, "uncached_prompt_tokens"),
        ],
        metadata={"sqlite_view": "evernight_agent_runs"},
    )


def _agent_trace_events_source() -> DataSourceDefinition:
    return DataSourceDefinition(
        source_id="agent_trace_events",
        name="Agent trace events",
        description="Persisted agent trace events joined to run metadata.",
        fields=[
            _field("event_id", "Event ID", DataFieldType.INTEGER),
            _field("run_id", "Run ID", DataFieldType.STRING),
            _field("event_type", "Event type", DataFieldType.STRING),
            _field("step_type", "Step type", DataFieldType.STRING),
            _field("tool_name", "Tool name", DataFieldType.STRING),
            _field("approval_status", "Approval status", DataFieldType.STRING),
            _field("error_type", "Error type", DataFieldType.STRING),
            _field("memory_id", "Memory ID", DataFieldType.STRING),
            _field("is_tool_call", "Is tool call", DataFieldType.BOOLEAN),
            _field("is_tool_success", "Is tool success", DataFieldType.BOOLEAN),
            _field("is_tool_failure", "Is tool failure", DataFieldType.BOOLEAN),
            _field("is_tool_approval_required", "Is tool approval required", DataFieldType.BOOLEAN),
            _field("is_memory_write", "Is memory write", DataFieldType.BOOLEAN),
            _field("memory_write_session_id", "Memory write session ID", DataFieldType.STRING),
            _field("provider_id", "Provider ID", DataFieldType.STRING),
            _field("model_id", "Model ID", DataFieldType.STRING),
            _field("context_id", "Context ID", DataFieldType.STRING),
            _field("session_id", "Session ID", DataFieldType.STRING),
            _field("created_at", "Created at", DataFieldType.DATETIME),
            _field("event_day", "Event day", DataFieldType.STRING),
        ],
        metrics=[
            _metric("event_count", "Event count", DataAggregation.COUNT),
            _metric("distinct_run_count", "Distinct run count", DataAggregation.DISTINCT_COUNT, "run_id"),
            _metric("distinct_session_count", "Distinct session count", DataAggregation.DISTINCT_COUNT, "session_id"),
            _metric("tool_call_count", "Tool call count", DataAggregation.SUM, "is_tool_call"),
            _metric("tool_success_count", "Tool success count", DataAggregation.SUM, "is_tool_success"),
            _metric("tool_failure_count", "Tool failure count", DataAggregation.SUM, "is_tool_failure"),
            _metric("tool_approval_required_count", "Tool approval required count", DataAggregation.SUM, "is_tool_approval_required"),
            _metric("memory_write_count", "Memory write count", DataAggregation.SUM, "is_memory_write"),
            _metric("sessions_with_memory_write_count", "Sessions with memory write count", DataAggregation.DISTINCT_COUNT, "memory_write_session_id"),
        ],
        metadata={"sqlite_view": "evernight_agent_trace_events"},
    )


def _sessions_source() -> DataSourceDefinition:
    return DataSourceDefinition(
        source_id="sessions",
        name="Sessions",
        description="Persisted conversation sessions.",
        fields=[
            _field("session_id", "Session ID", DataFieldType.STRING),
            _field("title", "Title", DataFieldType.STRING),
            _field("context_id", "Context ID", DataFieldType.STRING),
            _field("provider_id", "Provider ID", DataFieldType.STRING),
            _field("model_id", "Model ID", DataFieldType.STRING),
            _field("status", "Status", DataFieldType.STRING),
            _field("created_at", "Created at", DataFieldType.DATETIME),
            _field("updated_at", "Updated at", DataFieldType.DATETIME),
            _field("created_day", "Created day", DataFieldType.STRING),
            _field("updated_day", "Updated day", DataFieldType.STRING),
        ],
        metrics=[
            _metric("session_count", "Session count", DataAggregation.COUNT),
            _metric("distinct_provider_count", "Distinct provider count", DataAggregation.DISTINCT_COUNT, "provider_id"),
            _metric("distinct_model_count", "Distinct model count", DataAggregation.DISTINCT_COUNT, "model_id"),
        ],
        metadata={"sqlite_view": "evernight_sessions"},
    )


def _contexts_source() -> DataSourceDefinition:
    return DataSourceDefinition(
        source_id="contexts",
        name="Contexts",
        description="Persisted model-visible context windows.",
        fields=[
            _field("context_id", "Context ID", DataFieldType.STRING),
            _field("message_count", "Message count", DataFieldType.INTEGER),
        ],
        metrics=[
            _metric("context_count", "Context count", DataAggregation.COUNT),
            _metric("total_messages", "Total messages", DataAggregation.SUM, "message_count"),
            _metric("average_message_count", "Average message count", DataAggregation.AVERAGE, "message_count"),
        ],
        metadata={"sqlite_view": "evernight_contexts"},
    )


def _memories_source() -> DataSourceDefinition:
    return DataSourceDefinition(
        source_id="memories",
        name="Memories",
        description="Persisted memories.",
        fields=[
            _field("memory_id", "Memory ID", DataFieldType.STRING),
            _field("kind", "Kind", DataFieldType.STRING),
            _field("scope", "Scope", DataFieldType.STRING),
            _field("scope_id", "Scope ID", DataFieldType.STRING),
            _field("priority", "Priority", DataFieldType.INTEGER),
            _field("is_enabled", "Is enabled", DataFieldType.BOOLEAN),
        ],
        metrics=[
            _metric("memory_count", "Memory count", DataAggregation.COUNT),
            _metric("average_priority", "Average priority", DataAggregation.AVERAGE, "priority"),
        ],
        metadata={"sqlite_view": "evernight_memories"},
    )


def _field(
    field_id: str,
    name: str,
    field_type: DataFieldType,
) -> DataFieldDefinition:
    return DataFieldDefinition(
        field_id=field_id,
        name=name,
        field_type=field_type,
    )


def _metric(
    metric_id: str,
    name: str,
    aggregation: DataAggregation,
    field_id: str | None = None,
) -> DataMetricDefinition:
    return DataMetricDefinition(
        metric_id=metric_id,
        name=name,
        aggregation=aggregation,
        field_id=field_id,
    )


def _replace_sqlite_view(
    connection: sqlite3.Connection,
    view_name: str,
    view_sql: str,
) -> None:
    connection.execute(f"DROP VIEW IF EXISTS {view_name}")
    connection.execute(view_sql)
