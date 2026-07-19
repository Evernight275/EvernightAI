from dataclasses import dataclass

from EvernightAI.infra.registrations.data_analysis.runtime_sqlite import (
    sqlite_runtime_data_analysis_sources,
)


@dataclass(frozen=True)
class RuntimeStatisticCoverageRule:
    statistic_id: str
    source_id: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...] = ()
    filter_fields: tuple[str, ...] = ()


RUNTIME_STATISTIC_COVERAGE_RULES = [
    RuntimeStatisticCoverageRule(
        statistic_id="daily_agent_run_count",
        source_id="agent_runs",
        metrics=("run_count",),
        dimensions=("created_day",),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="agent_run_success_failure_pause_share",
        source_id="agent_runs",
        metrics=("successful_run_rate", "failed_run_rate", "paused_run_rate"),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="average_tool_rounds",
        source_id="agent_runs",
        metrics=("average_tool_rounds",),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="provider_call_count",
        source_id="agent_runs",
        metrics=("run_count",),
        dimensions=("provider_id",),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="daily_new_session_count",
        source_id="sessions",
        metrics=("session_count",),
        dimensions=("created_day",),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="provider_model_request_count",
        source_id="agent_runs",
        metrics=("run_count",),
        dimensions=("provider_id", "model_id"),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="provider_model_token_usage",
        source_id="agent_runs",
        metrics=(
            "prompt_tokens_total",
            "completion_tokens_total",
            "total_tokens_total",
            "cached_prompt_tokens_total",
            "cache_observed_prompt_tokens_total",
            "uncached_prompt_tokens_total",
        ),
        dimensions=("provider_id", "model_id"),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="average_context_message_count",
        source_id="contexts",
        metrics=("average_message_count",),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="sessions_with_memory_write_count",
        source_id="agent_trace_events",
        metrics=("sessions_with_memory_write_count",),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="tool_call_count_by_tool",
        source_id="agent_trace_events",
        metrics=("tool_call_count",),
        dimensions=("tool_name",),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="tool_success_failure_count",
        source_id="agent_trace_events",
        metrics=("tool_success_count", "tool_failure_count"),
        dimensions=("tool_name",),
    ),
    RuntimeStatisticCoverageRule(
        statistic_id="approval_required_tool_call_count",
        source_id="agent_trace_events",
        metrics=("tool_approval_required_count",),
        dimensions=("tool_name",),
    ),
]


def test_runtime_sqlite_data_analysis_sources_cover_target_statistics() -> None:
    sources = {
        source.source_id: source
        for source in sqlite_runtime_data_analysis_sources(include_agent_sources=True)
    }

    for rule in RUNTIME_STATISTIC_COVERAGE_RULES:
        source = sources[rule.source_id]
        metrics = {metric.metric_id for metric in source.metrics}
        fields = {field.field_id for field in source.fields}

        assert sorted(set(rule.metrics) - metrics) == [], rule.statistic_id
        assert sorted(set(rule.dimensions) - fields) == [], rule.statistic_id
        assert sorted(set(rule.filter_fields) - fields) == [], rule.statistic_id
