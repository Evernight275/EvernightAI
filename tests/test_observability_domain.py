from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from EvernightAI.core.schema.agent import AgentTraceEvent, AgentTraceEventType
from EvernightAI.core.schema.log import Log, LogLevel
from EvernightAI.core.schema.trace import TraceEvent, TraceSubject


def test_trace_event_names_cross_domain_semantic_event_shape() -> None:
    event = TraceEvent(
        sequence=1,
        trace_id="trace-1",
        event_type="provider.chat.completed",
        source="application.chat",
        subject=TraceSubject(kind="context", subject_id="ctx-1"),
        summary="Provider chat completed",
        occurred_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
    )

    assert event.trace_id == "trace-1"
    assert event.subject is not None
    assert event.subject.kind == "context"
    assert event.summary == "Provider chat completed"


def test_agent_trace_event_is_agent_specific_trace_event() -> None:
    event = AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED)

    assert isinstance(event, TraceEvent)
    assert event.event_type is AgentTraceEventType.RUN_STARTED


def test_log_is_separate_from_trace_but_can_correlate_to_it() -> None:
    log = Log(
        sequence=1,
        level=LogLevel.WARNING,
        source="EvernightAI.application.agent",
        message="tool execution needs approval",
        trace_id="trace-1",
        subject=TraceSubject(kind="agent_run", subject_id="run-1"),
    )

    assert log.level is LogLevel.WARNING
    assert log.trace_id == "trace-1"
    assert log.subject is not None
    assert log.subject.subject_id == "run-1"


def test_observability_sequences_are_positive_when_present() -> None:
    with pytest.raises(ValidationError):
        TraceEvent(sequence=0, event_type="invalid")

    with pytest.raises(ValidationError):
        Log(sequence=0, level=LogLevel.INFO, source="test", message="invalid")
