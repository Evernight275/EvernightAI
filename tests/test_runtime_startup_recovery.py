import asyncio
import subprocess
import sys
import time
from datetime import datetime, timezone

import pytest

from EvernightAI.application.agent_recovery import recover_interrupted_agent_runs
from EvernightAI.bootstrap.config import create_runtime_from_config
from EvernightAI.bootstrap.http import create_app
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import (
    DeferredAgentRunRecovery,
    create_sqlite_runtime,
)
from EvernightAI.core.domain.memory import BasicMemoryStrategy, BasicMemoryWriteStrategy
from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.schema.agent import AgentRunResult, AgentRunStatus
from EvernightAI.core.schema.content import ChatResponse, Content, MessageRole
from EvernightAI.core.schema.memory import MemoryItem
from EvernightAI.infra.adapters.agent.sqlite import (
    SQLiteAgentRunStateRegister,
    SQLiteAgentTraceRegister,
)
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor
from EvernightAI.interface.cli.config import parse_config
from tests.test_application_agent import make_message
from tests.test_sqlite_runtime_foundation import _running_state


@pytest.mark.asyncio
async def test_runtime_construction_and_interface_creation_do_not_touch_database(
    tmp_path,
):
    database = tmp_path / "new" / "runtime.sqlite3"
    runtime = create_sqlite_runtime(database)
    tools = runtime.tool_register.list_tools()
    try:
        assert any(tool.name == "generate_image" for tool in tools)
        create_interface(runtime)
        create_interface(runtime)
        assert runtime.tool_register.list_tools() == tools
        assert not database.parent.exists()
        await runtime.initialize()
        assert database.exists()
        assert runtime.is_ready
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_runtime_close_without_initialize_does_not_create_database(tmp_path):
    database = tmp_path / "new" / "runtime.sqlite3"
    await create_sqlite_runtime(database).close()
    assert not database.parent.exists()


@pytest.mark.asyncio
async def test_config_defers_sandbox_workspace_creation_until_initialize(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "work"
    monkeypatch.setattr(
        "EvernightAI.bootstrap.config.create_sandbox_from_config",
        lambda *a, **kw: SubprocessSandboxExecutor(),
    )
    runtime = create_runtime_from_config(
        parse_config(
            {
                "runtime": {
                    "database_path": str(tmp_path / "runtime.sqlite3"),
                    "sandbox_backend": "bubblewrap",
                    "sandbox": {"workspace_root": str(workspace)},
                },
            }
        )
    )
    try:
        assert not workspace.exists()
        await runtime.initialize()
        assert workspace.is_dir()
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_recovery_waits_for_initialize(tmp_path):
    database = tmp_path / "runtime.sqlite3"
    states = SQLiteAgentRunStateRegister(database)
    state = _running_state("run")
    state.history.started_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    states.save_state(state)
    runtime = create_sqlite_runtime(database)
    try:
        assert states.get_state("run").status is AgentRunStatus.RUNNING
        await runtime.initialize()
        await runtime.initialize()
        assert states.get_state("run").status is AgentRunStatus.PAUSED
        assert runtime.agent_trace_register is not None
        assert len(runtime.agent_trace_register.list_events("run")) == 1
    finally:
        states.close()
        await runtime.close()


@pytest.mark.asyncio
async def test_recovery_rechecks_renewed_leases(tmp_path):
    database = tmp_path / "runtime.sqlite3"
    states = SQLiteAgentRunStateRegister(database)
    states.save_state(_running_state("run"))
    generation = states.acquire_lease("run", "worker", ttl_seconds=0.4)
    runtime = create_sqlite_runtime(database)
    recovery = DeferredAgentRunRecovery(
        runtime, interval_seconds=0.05, margin_seconds=0
    )
    try:
        await recovery.start()
        assert states.heartbeat_lease("run", "worker", generation, ttl_seconds=0.8)
        await asyncio.sleep(0.45)
        assert states.get_state("run").status is AgentRunStatus.RUNNING
        async with asyncio.timeout(3):
            while states.get_state("run").status is AgentRunStatus.RUNNING:
                await asyncio.sleep(0.05)
        assert states.get_execution_lease("run") is None
    finally:
        await recovery.close()
        await runtime.close()
        states.close()


@pytest.mark.asyncio
async def test_recovery_watches_new_runs_and_preserves_runs_waiting_for_a_lease(
    tmp_path,
):
    database = tmp_path / "runtime.sqlite3"
    runtime = create_sqlite_runtime(database)
    recovery = DeferredAgentRunRecovery(runtime, interval_seconds=0.02)
    states = runtime.agent_state_register
    assert states is not None
    try:
        await recovery.start()
        pending = _running_state("new")
        pending.history.started_at = datetime.now(timezone.utc)
        states.save_state(pending)
        await asyncio.sleep(0.1)
        assert states.get_state("new").status is AgentRunStatus.RUNNING
        states.acquire_lease("new", "crashed-worker", ttl_seconds=-1)
        async with asyncio.timeout(3):
            while states.get_state("new").status is AgentRunStatus.RUNNING:
                await asyncio.sleep(0.02)
    finally:
        await recovery.close()
        await runtime.close()


def test_recovery_rolls_back_trace_and_preserves_lease_on_failure(
    tmp_path, monkeypatch
):
    database = tmp_path / "runtime.sqlite3"
    states = SQLiteAgentRunStateRegister(database)
    traces = SQLiteAgentTraceRegister(database)
    states.save_state(_running_state("run"))
    states.acquire_lease("run", "crashed", ttl_seconds=-1)

    def fail_save(*args, **kwargs):
        raise RuntimeError("save failed")

    monkeypatch.setattr(states, "save_state", fail_save)
    try:
        with pytest.raises(RuntimeError, match="save failed"):
            recover_interrupted_agent_runs(states, traces)
        assert traces.list_events("run") == []
        assert states.get_state("run").status is AgentRunStatus.RUNNING
        assert states.get_execution_lease("run") is not None
    finally:
        states.close()
        traces.close()


WORKER = """
import sys
import time
from pathlib import Path
from EvernightAI.application.agent_recovery import recover_interrupted_agent_runs
from EvernightAI.infra.adapters.agent.sqlite import SQLiteAgentRunStateRegister, SQLiteAgentTraceRegister
root, name = Path(sys.argv[1]), sys.argv[2]
states = SQLiteAgentRunStateRegister(root / 'runtime.sqlite3')
traces = SQLiteAgentTraceRegister(root / 'runtime.sqlite3')
states.get_state('run')
(root / ('ready-' + name)).touch()
deadline = time.monotonic() + 10
while not all((root / ('ready-' + worker)).exists() for worker in ['a', 'b']):
    assert time.monotonic() < deadline, 'worker barrier timeout'
    time.sleep(0.01)
print(recover_interrupted_agent_runs(states, traces))
states.close()
traces.close()
"""


def test_two_processes_recover_a_run_once(tmp_path):
    states = SQLiteAgentRunStateRegister(tmp_path / "runtime.sqlite3")
    traces = SQLiteAgentTraceRegister(tmp_path / "runtime.sqlite3")
    states.save_state(_running_state("run"))
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", WORKER, str(tmp_path), name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for name in ["a", "b"]
    ]
    try:
        counts = []
        for worker in workers:
            output, error = worker.communicate(timeout=15)
            assert worker.returncode == 0, error
            counts.append(int(output.strip()))
        assert sorted(counts) == [0, 1]
        events = traces.list_events("run")
        state = states.get_state("run")
        assert len(events) == 1
        assert state.applied_trace_sequence == events[0].sequence
        assert state.status is AgentRunStatus.PAUSED
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.wait(timeout=5)
        states.close()
        traces.close()


def test_recovery_cannot_clear_a_concurrently_acquired_lease(tmp_path, monkeypatch):
    database = tmp_path / "runtime.sqlite3"
    states = SQLiteAgentRunStateRegister(database)
    traces = SQLiteAgentTraceRegister(database)
    states.save_state(_running_state("run"))
    states.acquire_lease("run", "dead", ttl_seconds=-1)
    script = """
import sys
import time
from pathlib import Path
from EvernightAI.infra.adapters.agent.sqlite import SQLiteAgentRunStateRegister
root = Path(sys.argv[1])
states = SQLiteAgentRunStateRegister(root / 'runtime.sqlite3')
states.get_state('run')
(root / 'ready').touch()
deadline = time.monotonic() + 10
while not (root / 'read-lease').exists():
    assert time.monotonic() < deadline
    time.sleep(0.01)
(root / 'attempting').touch()
states.acquire_lease('run', 'live-worker', ttl_seconds=60)
(root / 'acquired').touch()
states.close()
"""
    worker = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def wait_for(name):
        deadline = time.monotonic() + 5
        while not (tmp_path / name).exists():
            assert worker.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)

    get_lease = states.get_execution_lease

    def read_then_allow_takeover(run_id, **kwargs):
        lease = get_lease(run_id, **kwargs)
        (tmp_path / "read-lease").touch()
        wait_for("attempting")
        time.sleep(0.05)
        assert not (tmp_path / "acquired").exists()
        return lease

    try:
        wait_for("ready")
        monkeypatch.setattr(states, "get_execution_lease", read_then_allow_takeover)
        assert recover_interrupted_agent_runs(states, traces) == 1
        _, error = worker.communicate(timeout=10)
        assert worker.returncode == 0, error
        lease = get_lease("run")
        assert lease is not None and lease.owner == "live-worker"
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=5)
        states.close()
        traces.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["none", "None", " null ", "disabled"])
async def test_env_can_disable_all_trace_cleanup(tmp_path, monkeypatch, value):
    monkeypatch.setenv("EVERNIGHTAI_TRACE_RETENTION_DAYS", value)
    monkeypatch.setenv("EVERNIGHTAI_TRACE_MAX_EVENTS", value)
    calls = []
    monkeypatch.setattr(
        SQLiteAgentTraceRegister, "prune_events", lambda *a, **kw: calls.append(kw)
    )
    app = create_app(database_path=tmp_path / "runtime.sqlite3")
    async with app.router.lifespan_context(app):
        assert calls == []


@pytest.mark.parametrize("value", ["-1", "invalid"])
def test_env_rejects_invalid_trace_limits_before_opening_database(
    tmp_path, monkeypatch, value
):
    monkeypatch.setenv("EVERNIGHTAI_TRACE_RETENTION_DAYS", value)
    database = tmp_path / "runtime.sqlite3"
    with pytest.raises(ConfigurationError, match="EVERNIGHTAI_TRACE_RETENTION_DAYS"):
        create_app(database_path=database)
    assert not database.exists()


@pytest.mark.asyncio
async def test_config_can_disable_memory_selection_and_writing(tmp_path):
    runtime = create_runtime_from_config(
        parse_config(
            {
                "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
                "memory_strategy": {"selection": "disabled", "write": "disabled"},
            }
        )
    )
    try:
        assert (
            runtime.memory_strategy.select(
                [MemoryItem(memory_id="fact", content="saved")]
            ).memories
            == []
        )
        state = _running_state("run")
        state.request.write_memory = True
        state.request.messages = [make_message("Remember this fact")]
        result = AgentRunResult(
            response=ChatResponse(
                model_id="model", message=Content(role=MessageRole.ASSISTANT)
            )
        )
        assert (
            runtime.memory_write_strategy.create_memories(state.request, result) == []
        )
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_sqlite_factory_accepts_custom_memory_policies(tmp_path):
    selection = BasicMemoryStrategy()
    write = BasicMemoryWriteStrategy()
    runtime = create_sqlite_runtime(
        tmp_path / "runtime.sqlite3",
        memory_strategy=selection,
        memory_write_strategy=write,
    )
    assert runtime.memory_strategy is selection
    assert runtime.memory_write_strategy is write
    await runtime.close()
