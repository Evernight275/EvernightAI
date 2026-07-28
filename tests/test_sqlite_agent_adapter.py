from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
    AgentTraceEvent,
    AgentTraceEventType,
    ToolExecutionAttempt,
    ToolExecutionStatus,
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
    SQLiteToolExecutionRegister,
)
from EvernightAI.bootstrap.runtime import (
    create_sqlite_agent_state_register,
    create_sqlite_agent_trace_register,
    create_sqlite_tool_execution_register,
)
from EvernightAI.core.schema.tool import (
    ToolCall,
    ToolCallResult,
    ToolReplayPolicy,
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
    assert register.append_event("run-1", started) == 1
    assert register.append_event("run-1", paused) == 2
    register.close()

    reopened = SQLiteAgentTraceRegister(database_path)

    try:
        assert reopened.list_events("run-1") == [started, paused]
        assert [event.sequence for event in reopened.list_events("run-1")] == [1, 2]
        assert reopened.list_events("run-1", after_sequence=1) == [paused]
        assert reopened.list_events("run-1", limit=1) == [started]
        assert reopened.list_events("missing") == []

        reopened.clear_events("run-1")

        assert reopened.list_events("run-1") == []
    finally:
        reopened.close()


def test_sqlite_agent_trace_register_migrates_legacy_events(tmp_path: Path) -> None:
    database_path = make_database_path(tmp_path)
    started = make_event(AgentTraceEventType.RUN_STARTED)
    paused = make_event(AgentTraceEventType.RUN_PAUSED)
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE agent_trace_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.executemany(
        "INSERT INTO agent_trace_events (run_id, payload) VALUES (?, ?)",
        [
            ("run-1", started.model_dump_json(exclude_none=True)),
            ("run-1", paused.model_dump_json(exclude_none=True)),
            ("run-2", started.model_dump_json(exclude_none=True)),
        ],
    )
    connection.commit()
    connection.close()

    register = SQLiteAgentTraceRegister(database_path)

    try:
        assert [event.sequence for event in register.list_events("run-1")] == [1, 2]
        assert [event.sequence for event in register.list_events("run-2")] == [1]
        assert register.append_event(
            "run-1",
            make_event(AgentTraceEventType.RUN_STOPPED),
        ) == 3
    finally:
        register.close()


def test_sqlite_agent_trace_register_allocates_concurrent_sequences(
    tmp_path: Path,
) -> None:
    database_path = make_database_path(tmp_path)
    register = SQLiteAgentTraceRegister(database_path)
    register.close()

    def append_event(_: int) -> int:
        worker_register = SQLiteAgentTraceRegister(database_path)
        try:
            return worker_register.append_event(
                "run-1",
                make_event(AgentTraceEventType.CHAT_DELTA),
            )
        finally:
            worker_register.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        sequences = list(executor.map(append_event, range(12)))

    reopened = SQLiteAgentTraceRegister(database_path)
    try:
        persisted_sequences = [
            event.sequence for event in reopened.list_events("run-1")
        ]
    finally:
        reopened.close()

    assert sorted(sequences) == list(range(1, 13))
    assert persisted_sequences == list(range(1, 13))


def test_sqlite_tool_execution_register_persists_attempts_and_cascades(
    tmp_path: Path,
) -> None:
    database_path = make_database_path(tmp_path)
    state_register = SQLiteAgentRunStateRegister(database_path)
    state_register.save_state(make_state())
    register = SQLiteToolExecutionRegister(database_path)
    attempt = ToolExecutionAttempt(
        run_id="run-1",
        tool_call_id="call-1",
        attempt=1,
        tool_name="read_file",
        status=ToolExecutionStatus.STARTED,
        replay_policy=ToolReplayPolicy.SAFE,
        idempotency_key="run-1:call-1",
        tool_call=ToolCall(
            tool_call_id="call-1",
            tool_call={"name": "read_file", "arguments": {"path": "a.txt"}},
        ),
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )

    register.create_attempt(attempt)
    with pytest.raises(AgentStateError, match="already exists"):
        register.create_attempt(attempt)

    completed = attempt.model_copy(
        update={
            "status": ToolExecutionStatus.COMPLETED,
            "result": ToolCallResult(
                tool_call_id="call-1",
                tool_call_result={"content": "hello"},
            ),
            "finished_at": datetime.now(timezone.utc),
        }
    )
    register.save_attempt(completed)
    assert register.get_attempt("run-1", "call-1", 1) == completed
    assert register.list_attempts("run-1") == [completed]

    state_register.delete_state("run-1")
    assert register.list_attempts("run-1") == []
    register.close()
    state_register.close()


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

    execution_register = create_sqlite_tool_execution_register(database_path)
    try:
        assert isinstance(execution_register, SQLiteToolExecutionRegister)
    finally:
        execution_register.close()
