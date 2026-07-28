import asyncio
from pathlib import Path
import sqlite3

import pytest

from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.application.agent import AgentRunApplication, AgentRunMetadata
from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.error.agent import AgentRunCanceledError, AgentRunTimeoutError
from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.error.context import ContextNotFoundError, ContextStateError
from EvernightAI.core.error.memory import MemoryNotFoundError
from EvernightAI.core.error.session import SessionNotFoundError
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
    AgentStep,
    AgentStepType,
    AgentTraceEvent,
    AgentTraceEventType,
)
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.content import ChatRequest, ChatResponse, Content, MessageRole
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.session import Session, SessionStatus
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.adapters.agent.executor import SingleProcessAgentRunExecutor
from EvernightAI.infra.adapters.agent.sqlite import (
    SQLiteAgentRunStateRegister,
    SQLiteAgentTraceRegister,
)
from EvernightAI.infra.adapters.context.sqlite import SQLiteContextRegister
from EvernightAI.infra.adapters.memory.sqlite import SQLiteMemoryRegister
from EvernightAI.infra.adapters.providers.secrets import EnvironmentProviderSecretResolver
from EvernightAI.infra.adapters.providers.sqlite import SQLiteProviderConfigStore
from EvernightAI.infra.adapters.session.sqlite import SQLiteSessionRegister
from EvernightAI.infra.sqlite import SQLiteMigrationRunner, connect_sqlite


def test_migration_runner_versions_schema_and_configures_connections(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"

    assert SQLiteMigrationRunner(database_path).run() == 3
    assert SQLiteMigrationRunner(database_path).run() == 3

    connection = connect_sqlite(database_path)
    try:
        versions = connection.execute(
            "SELECT version FROM evernight_schema_migrations ORDER BY version"
        ).fetchall()
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert versions == [(1,), (2,), (3,)]
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (5000,)
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert "idx_agent_runs_status" in indexes
        assert "idx_agent_trace_run_sequence" in indexes
    finally:
        connection.close()


def test_sqlite_context_append_uses_revision_cas(tmp_path: Path) -> None:
    register = SQLiteContextRegister(tmp_path / "runtime.sqlite3")
    register.register(Context(context_id="ctx-1"))

    first = register.append_message(
        "ctx-1",
        Content(role=MessageRole.USER),
        expected_revision=0,
    )

    assert first.revision == 1
    with pytest.raises(ContextStateError, match="expected 0"):
        register.append_message(
            "ctx-1",
            Content(role=MessageRole.ASSISTANT),
            expected_revision=0,
        )
    register.close()


def test_sqlite_stores_enforce_principal_scope(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    owner_scope = PrincipalScope(owner_id="owner-1")
    other_scope = PrincipalScope(owner_id="owner-2")
    contexts = SQLiteContextRegister(database_path)
    memories = SQLiteMemoryRegister(database_path)
    sessions = SQLiteSessionRegister(database_path)
    agent_states = SQLiteAgentRunStateRegister(database_path)
    contexts.register(Context(context_id="ctx-1", owner_id="owner-1"))
    memories.register(
        MemoryItem(memory_id="memory-1", owner_id="owner-1", content="private")
    )
    sessions.register(
        Session(
            session_id="session-1",
            context_id="ctx-1",
            owner_id="owner-1",
        )
    )
    agent_states.create_state(_running_state("run-1", owner_id="owner-1"))

    assert contexts.get("ctx-1", principal_scope=owner_scope).owner_id == "owner-1"
    assert memories.get("memory-1", principal_scope=owner_scope).owner_id == "owner-1"
    assert sessions.get("session-1", principal_scope=owner_scope).owner_id == "owner-1"
    assert agent_states.get_state("run-1", principal_scope=owner_scope).owner_id == "owner-1"
    with pytest.raises(ContextNotFoundError):
        contexts.get("ctx-1", principal_scope=other_scope)
    with pytest.raises(MemoryNotFoundError):
        memories.get("memory-1", principal_scope=other_scope)
    with pytest.raises(SessionNotFoundError):
        sessions.get("session-1", principal_scope=other_scope)
    with pytest.raises(AgentStateError):
        agent_states.get_state("run-1", principal_scope=other_scope)
    assert contexts.list_contexts(principal_scope=other_scope) == []
    assert memories.list_memories(principal_scope=other_scope) == []
    assert sessions.list_sessions(principal_scope=other_scope) == []
    assert agent_states.query_states(principal_scope=other_scope) == []

    contexts.close()
    memories.close()
    sessions.close()
    agent_states.close()


def test_sqlite_stores_apply_cursor_limit_and_filters(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    contexts = SQLiteContextRegister(database_path)
    memories = SQLiteMemoryRegister(database_path)
    sessions = SQLiteSessionRegister(database_path)
    agent_states = SQLiteAgentRunStateRegister(database_path)

    contexts.register(Context(context_id="ctx-1", owner_id="owner-1"))
    contexts.register(Context(context_id="ctx-2", owner_id="owner-1"))
    contexts.register(Context(context_id="ctx-3", owner_id="owner-2"))
    memories.register(
        MemoryItem(
            memory_id="memory-1",
            owner_id="owner-1",
            content="low relevance",
            relevance=0.2,
        )
    )
    memories.register(
        MemoryItem(
            memory_id="memory-2",
            owner_id="owner-1",
            content="high relevance",
            relevance=0.8,
        )
    )
    memories.register(
        MemoryItem(
            memory_id="memory-3",
            owner_id="owner-2",
            content="other owner",
            relevance=0.9,
        )
    )
    sessions.register(
        Session(
            session_id="session-1",
            context_id="ctx-1",
            owner_id="owner-1",
            provider_id="provider-1",
            model_id="model-1",
        )
    )
    sessions.register(
        Session(
            session_id="session-2",
            context_id="ctx-2",
            owner_id="owner-1",
            provider_id="provider-1",
            model_id="model-1",
            status=SessionStatus.ARCHIVED,
        )
    )
    sessions.register(
        Session(
            session_id="session-3",
            context_id="ctx-3",
            owner_id="owner-2",
            provider_id="provider-2",
            model_id="model-2",
        )
    )
    agent_states.create_state(_running_state("run-1", owner_id="owner-1"))
    agent_states.create_state(_running_state("run-2", owner_id="owner-1"))
    agent_states.create_state(_running_state("run-3", owner_id="owner-2"))

    try:
        assert [
            context.context_id
            for context in contexts.list_contexts(
                cursor="ctx-1",
                limit=1,
                owner_id="owner-1",
            )
        ] == ["ctx-2"]
        assert [
            memory.memory_id
            for memory in memories.list_memories(
                owner_id="owner-1",
                query=MemoryQuery(minimum_relevance=0.5),
            )
        ] == ["memory-2"]
        assert [
            session.session_id
            for session in sessions.list_sessions(
                owner_id="owner-1",
                status=SessionStatus.ARCHIVED,
                provider_id="provider-1",
                model_id="model-1",
            )
        ] == ["session-2"]
        assert [
            state.run_id
            for state in agent_states.query_states(
                cursor="run-1",
                limit=1,
                owner_id="owner-1",
                status=AgentRunStatus.RUNNING,
                context_id="ctx-1",
            )
        ] == ["run-2"]
    finally:
        contexts.close()
        memories.close()
        sessions.close()
        agent_states.close()


def test_provider_config_store_never_persists_raw_api_key(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    store = SQLiteProviderConfigStore(database_path)
    store.save(
        ProviderConfig(
            provider_id="provider-1",
            name="Provider",
            type=ProviderType.OPENAI,
            api_key="raw-secret-value",
            api_key_secret_ref="env:PROVIDER_TEST_KEY",
        )
    )

    stored = store.get("provider-1")
    connection = sqlite3.connect(database_path)
    try:
        raw_payload = connection.execute(
            "SELECT payload FROM provider_configs WHERE provider_id = 'provider-1'"
        ).fetchone()[0]
    finally:
        connection.close()
        store.close()

    assert stored.api_key is None
    assert stored.api_key_secret_ref == "env:PROVIDER_TEST_KEY"
    assert "raw-secret-value" not in raw_payload


@pytest.mark.asyncio
async def test_provider_manager_restores_config_with_environment_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROVIDER_TEST_KEY", "injected-secret")
    store = SQLiteProviderConfigStore(tmp_path / "runtime.sqlite3")
    store.save(
        ProviderConfig(
            provider_id="provider-1",
            name="Provider",
            type=ProviderType.OPENAI,
            api_key_secret_ref="env:PROVIDER_TEST_KEY",
        )
    )
    built: list[ProviderConfig] = []

    async def build(config: ProviderConfig) -> ProviderInstanceProtocol:
        built.append(config)
        return _ProviderInstance()

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(
        factory,
        config_store=store,
        secret_resolver=EnvironmentProviderSecretResolver(),
    )

    assert await manager.restore() == ["provider-1"]
    assert built[0].api_key == "injected-secret"
    assert (await manager.list_infos())[0].provider_id == "provider-1"

    await manager.close()
    store.close()


@pytest.mark.asyncio
async def test_single_process_executor_sends_cancel_signal_and_releases_lease(
    tmp_path: Path,
) -> None:
    register = SQLiteAgentRunStateRegister(tmp_path / "runtime.sqlite3")
    register.create_state(_running_state("run-1"))
    executor = SingleProcessAgentRunExecutor(register, default_timeout_seconds=None)
    started = asyncio.Event()

    async def operation() -> AgentRunState:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    task = asyncio.create_task(executor.execute("run-1", operation))
    await started.wait()
    assert executor.cancel("run-1") is True
    with pytest.raises(AgentRunCanceledError):
        await task

    connection = sqlite3.connect(tmp_path / "runtime.sqlite3")
    try:
        lease = connection.execute(
            "SELECT lease_owner, lease_expires_at FROM agent_run_states"
        ).fetchone()
    finally:
        connection.close()
        register.close()
    assert lease == (None, None)


@pytest.mark.asyncio
async def test_single_process_executor_enforces_timeout(tmp_path: Path) -> None:
    register = SQLiteAgentRunStateRegister(tmp_path / "runtime.sqlite3")
    register.create_state(_running_state("run-1"))
    executor = SingleProcessAgentRunExecutor(register, default_timeout_seconds=None)

    async def operation() -> AgentRunState:
        await asyncio.sleep(1)
        return register.get_state("run-1")

    with pytest.raises(AgentRunTimeoutError):
        await executor.execute("run-1", operation, timeout_seconds=0.01)
    register.close()


@pytest.mark.asyncio
async def test_single_process_executor_controls_stream_lifecycle(tmp_path: Path) -> None:
    register = SQLiteAgentRunStateRegister(tmp_path / "runtime.sqlite3")
    register.create_state(_running_state("run-1"))
    executor = SingleProcessAgentRunExecutor(register, default_timeout_seconds=None)
    started = asyncio.Event()

    async def events():
        started.set()
        await asyncio.Event().wait()
        if False:
            yield AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED)

    async def consume() -> None:
        async for _ in executor.stream("run-1", events):
            pass

    task = asyncio.create_task(consume())
    await started.wait()
    assert executor.cancel("run-1") is True
    with pytest.raises(AgentRunCanceledError):
        await task
    register.close()


@pytest.mark.asyncio
async def test_sqlite_bootstrap_recovers_legacy_running_agents(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    register = SQLiteAgentRunStateRegister(database_path)
    register.save_state(_running_state("run-1"))
    register.close()

    runtime = create_sqlite_runtime(database_path)
    try:
        state = runtime.agent_state_register.get_state("run-1")  # type: ignore[union-attr]
        events = runtime.agent_trace_register.list_events("run-1")  # type: ignore[union-attr]
        assert state.status is AgentRunStatus.PAUSED
        assert state.metadata["interruption_reason"] == "runtime_restart"
        runtime_metadata = state.metadata[AgentRunMetadata.RUNTIME_KEY]
        assert runtime_metadata["pause_source"] == "shutdown"
        assert runtime_metadata["recovery_eligible"] is True
        assert events[-1].metadata["reason"] == "shutdown"
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_sqlite_bootstrap_leaves_run_with_active_lease_running(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    register = SQLiteAgentRunStateRegister(database_path)
    register.save_state(_running_state("run-1"))
    register.acquire_lease("run-1", "another-executor", ttl_seconds=60)
    register.close()

    runtime = create_sqlite_runtime(database_path)
    try:
        state = runtime.agent_state_register.get_state("run-1")  # type: ignore[union-attr]
        events = runtime.agent_trace_register.list_events("run-1")  # type: ignore[union-attr]
        assert state.status is AgentRunStatus.RUNNING
        assert events == []
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_sqlite_bootstrap_expires_lease_and_blocks_unsafe_tool_recovery(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    register = SQLiteAgentRunStateRegister(database_path)
    state = _running_state("run-1")
    state.response = ChatResponse(
        model_id="model-1",
        message=Content(
            role=MessageRole.ASSISTANT,
            tool_calls=[
                ToolCall(
                    tool_call_id="call-1",
                    tool_call={"name": "write_file", "arguments": {}},
                )
            ],
        ),
        finish_reason="tool_calls",
    )
    state.steps.append(AgentStep(step_type=AgentStepType.CHAT, response=state.response))
    register.save_state(state)
    register.acquire_lease("run-1", "stopped-executor", ttl_seconds=60)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "UPDATE agent_run_states SET lease_expires_at = ? WHERE run_id = ?",
            ("2000-01-01T00:00:00+00:00", "run-1"),
        )
        connection.commit()
    finally:
        connection.close()
        register.close()

    runtime = create_sqlite_runtime(database_path)
    try:
        state_register = runtime.agent_state_register
        trace_register = runtime.agent_trace_register
        assert state_register is not None
        assert trace_register is not None
        state = state_register.get_state("run-1")
        runtime_metadata = state.metadata[AgentRunMetadata.RUNTIME_KEY]
        assert state.status is AgentRunStatus.PAUSED
        assert runtime_metadata["pause_source"] == "lease_expired"
        assert runtime_metadata["pause_checkpoint"] == "tool_execution_incomplete"
        assert runtime_metadata["recovery_eligible"] is False
        assert trace_register.list_events("run-1")[-1].metadata["reason"] == "lease_expired"

        with pytest.raises(AgentStateError, match="cannot resume safely"):
            await AgentRunApplication(runtime).resume("run-1", [])
    finally:
        await runtime.close()


def test_sqlite_trace_retention_keeps_latest_events(tmp_path: Path) -> None:
    register = SQLiteAgentTraceRegister(tmp_path / "runtime.sqlite3")
    for _ in range(5):
        register.append_event(
            "run-1",
            AgentTraceEvent(event_type=AgentTraceEventType.CHAT_DELTA),
        )

    assert register.prune_events(keep_latest=2) == 3
    assert [event.sequence for event in register.list_events("run-1")] == [4, 5]
    register.close()


def _running_state(run_id: str, *, owner_id: str | None = None) -> AgentRunState:
    return AgentRunState(
        run_id=run_id,
        owner_id=owner_id,
        request=AgentRunRequest(
            provider_id="provider-1",
            owner_id=owner_id,
            context_id="ctx-1",
            model_id="model-1",
            metadata={"run_id": run_id},
        ),
    )


class _ProviderInstance(ProviderInstanceProtocol):
    async def list_models(self) -> list[ProviderModelConfig]:
        return []

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return ProviderModelConfig(model_id=model_id)

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return False

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        raise NotImplementedError

    async def close(self) -> None:
        return None
