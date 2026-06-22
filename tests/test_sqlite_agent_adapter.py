from pathlib import Path

import pytest

from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
    AgentTraceEvent,
    AgentTraceEventType,
)
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.infra.adapters.agent.sqlite import (
    SQLiteAgentRunStateRegister,
    SQLiteAgentTraceRegister,
)
from EvernightAI.bootstrap.runtime import (
    create_sqlite_agent_state_register,
    create_sqlite_agent_trace_register,
)


def make_database_path(tmp_path: Path) -> Path:
    return tmp_path / "agent.sqlite3"


def make_state(run_id: str = "run-1") -> AgentRunState:
    return AgentRunState(
        run_id=run_id,
        request=AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            metadata={"run_id": run_id},
        ),
        status=AgentRunStatus.PAUSED,
        remaining_tool_rounds=1,
        metadata={"source": "test"},
    )


def make_event(event_type: AgentTraceEventType) -> AgentTraceEvent:
    return AgentTraceEvent(
        event_type=event_type,
        message=Content(
            role=MessageRole.ASSISTANT,
            content=[ContentPart(type=ContentPartType.TEXT, text=event_type.value)],
        ),
    )


def test_sqlite_agent_state_register_persists_states(tmp_path: Path) -> None:
    database_path = make_database_path(tmp_path)
    state = make_state()

    register = SQLiteAgentRunStateRegister(database_path)
    register.save_state(state)
    register.close()

    reopened = SQLiteAgentRunStateRegister(database_path)

    try:
        assert reopened.get_state("run-1") == state
        assert reopened.list_states() == [state]

        updated = state.model_copy(update={"status": AgentRunStatus.FINISHED})
        reopened.save_state(updated)

        assert reopened.get_state("run-1").status is AgentRunStatus.FINISHED
    finally:
        reopened.close()


def test_sqlite_agent_state_register_raises_for_missing_state(
    tmp_path: Path,
) -> None:
    register = SQLiteAgentRunStateRegister(make_database_path(tmp_path))

    try:
        with pytest.raises(AgentStateError):
            register.get_state("missing")

        with pytest.raises(AgentStateError):
            register.delete_state("missing")
    finally:
        register.close()


def test_sqlite_agent_trace_register_persists_events_in_order(
    tmp_path: Path,
) -> None:
    database_path = make_database_path(tmp_path)
    started = make_event(AgentTraceEventType.RUN_STARTED)
    paused = make_event(AgentTraceEventType.RUN_PAUSED)

    register = SQLiteAgentTraceRegister(database_path)
    register.append_event("run-1", started)
    register.append_event("run-1", paused)
    register.close()

    reopened = SQLiteAgentTraceRegister(database_path)

    try:
        assert reopened.list_events("run-1") == [started, paused]
        assert reopened.list_events("missing") == []

        reopened.clear_events("run-1")

        assert reopened.list_events("run-1") == []
    finally:
        reopened.close()


def test_sqlite_agent_bootstrap_helpers(tmp_path: Path) -> None:
    database_path = make_database_path(tmp_path)
    state_register = create_sqlite_agent_state_register(database_path)

    try:
        assert isinstance(state_register, SQLiteAgentRunStateRegister)
    finally:
        state_register.close()

    trace_register = create_sqlite_agent_trace_register(database_path)

    try:
        assert isinstance(trace_register, SQLiteAgentTraceRegister)
    finally:
        trace_register.close()
