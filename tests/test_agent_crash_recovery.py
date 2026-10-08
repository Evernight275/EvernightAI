import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from EvernightAI.application.agent import AgentRunApplication, AgentRunMetadata
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.schema.agent import (
    AgentRunStatus,
    ToolExecutionResolution,
    ToolExecutionStatus,
)
from EvernightAI.core.schema.content import MessageRole
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.core.schema.tool import ToolDefinition, ToolReplayPolicy
from EvernightAI.infra.adapters.agent.sqlite import (
    SQLiteAgentRunStateRegister,
    SQLiteToolExecutionRegister,
)
from tests.test_application_agent import FinalAnswerProvider, make_config


RUN_ID = "crash-run"
CRASH_EXIT_CODE = 70

# The tool kills its own process, so no finally block, lease release or
# shutdown hook gets to tidy the persisted state.
CRASH_SCRIPT = """
import asyncio
import os
import sys
from pathlib import Path
from EvernightAI.application.agent import AgentRunApplication
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.schema.agent import AgentRunRequest
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.tool import ToolDefinition, ToolReplayPolicy
from tests.test_application_agent import (
    ToolCallingProvider,
    make_config,
    make_message,
)

database, marker, replay_policy, run_id, exit_code = sys.argv[1:]

async def die_mid_tool(arguments):
    Path(marker).write_text('started', encoding='utf-8')
    os._exit(int(exit_code))

async def main():
    runtime = create_sqlite_runtime(database)
    async def build_provider(config):
        return ToolCallingProvider()
    tool = ToolDefinition(
        name='add',
        description='Add numbers',
        replay_policy=ToolReplayPolicy(replay_policy),
    )
    runtime.provider_factory.register(make_config().type, build_provider)
    runtime.tool_register.register(tool, die_mid_tool)
    await runtime.initialize()
    await runtime.providers.create(make_config())
    await runtime.contexts.create(Context(context_id='ctx-1'))
    await AgentRunApplication(runtime).start(
        AgentRunRequest(
            provider_id='provider-1',
            context_id='ctx-1',
            model_id='model-1',
            messages=[make_message('What is 1 + 2?')],
            tools=[tool],
            metadata={'run_id': run_id},
        )
    )

asyncio.run(main())
"""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replay_policy",
    [ToolReplayPolicy.SAFE, ToolReplayPolicy.NON_REPLAYABLE],
)
async def test_run_killed_during_tool_execution_recovers_after_restart(
    tmp_path: Path,
    replay_policy: ToolReplayPolicy,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    marker = tmp_path / "tool-started"

    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            CRASH_SCRIPT,
            str(database),
            str(marker),
            replay_policy.value,
            RUN_ID,
            str(CRASH_EXIT_CODE),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert crashed.returncode == CRASH_EXIT_CODE, crashed.stderr
    assert marker.exists(), crashed.stderr

    _assert_crash_left_run_mid_tool(database)
    _expire_lease(database)

    executed: list[dict[str, object]] = []
    provider = FinalAnswerProvider()
    runtime = create_sqlite_runtime(database)
    try:
        app = await _assemble(runtime, provider, executed, replay_policy)

        paused = app.get_state(RUN_ID)
        control = paused.metadata[AgentRunMetadata.RUNTIME_KEY]
        (unknown,) = app.list_tool_executions(RUN_ID)
        assert paused.status is AgentRunStatus.PAUSED
        assert control["pause_source"] == "lease_expired"
        assert unknown.status is ToolExecutionStatus.UNKNOWN
        assert unknown.idempotency_key == f"{RUN_ID}:tool-call-1"

        if replay_policy is ToolReplayPolicy.SAFE:
            assert control["pause_checkpoint"] == "tool_replay_ready"
            assert control["recovery_eligible"] is True
        else:
            assert control["pause_checkpoint"] == "tool_execution_incomplete"
            assert control["recovery_eligible"] is False
            with pytest.raises(AgentStateError, match="cannot resume safely"):
                await app.resume(RUN_ID, [])
            assert executed == []
            assert provider.requests == []
            await app.resolve_tool_execution(
                RUN_ID,
                unknown.tool_call_id,
                unknown.attempt,
                ToolExecutionResolution.CONFIRM_COMPLETED,
                result={"result": 3},
                reason="Verified externally",
            )

        resumed = await app.resume(RUN_ID, [])

        attempts = app.list_tool_executions(RUN_ID)
        context = await runtime.contexts.get("ctx-1")
        assert resumed.status is AgentRunStatus.FINISHED
        if replay_policy is ToolReplayPolicy.SAFE:
            assert executed == [{"left": 1, "right": 2}]
            assert [attempt.status for attempt in attempts] == [
                ToolExecutionStatus.UNKNOWN,
                ToolExecutionStatus.COMPLETED,
            ]
            assert attempts[1].idempotency_key == unknown.idempotency_key
        else:
            assert executed == []
            assert [attempt.status for attempt in attempts] == [
                ToolExecutionStatus.COMPLETED
            ]
        # The model call made before the crash is reused, not repeated.
        assert len(provider.requests) == 1
        assert [message.role for message in provider.requests[0].messages] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
            MessageRole.TOOL,
        ]
        assert [message.role for message in context.messages] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
            MessageRole.TOOL,
            MessageRole.ASSISTANT,
        ]
    finally:
        await runtime.close()


def _assert_crash_left_run_mid_tool(database: Path) -> None:
    states = SQLiteAgentRunStateRegister(database)
    executions = SQLiteToolExecutionRegister(database)
    try:
        lease = states.get_execution_lease(RUN_ID)
        (attempt,) = executions.list_attempts(RUN_ID)
        assert states.get_state(RUN_ID).status is AgentRunStatus.RUNNING
        assert attempt.status is ToolExecutionStatus.STARTED
        assert lease is not None
        assert lease.expires_at is not None
        assert lease.expires_at > datetime.now(timezone.utc)
    finally:
        executions.close()
        states.close()


def _expire_lease(database: Path) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE agent_run_states SET lease_expires_at = ? WHERE run_id = ?",
            ("2000-01-01T00:00:00+00:00", RUN_ID),
        )
        connection.commit()
    finally:
        connection.close()


async def _assemble(
    runtime: RuntimeKernel,
    provider: ProviderInstanceProtocol,
    executed: list[dict[str, object]],
    replay_policy: ToolReplayPolicy,
) -> AgentRunApplication:
    async def build_provider(config: ProviderConfig) -> ProviderInstanceProtocol:
        return provider

    async def add(arguments: dict[str, object]) -> dict[str, object]:
        executed.append(arguments)
        return {"result": 3}

    runtime.provider_factory.register(make_config().type, build_provider)
    runtime.tool_register.register(
        ToolDefinition(
            name="add",
            description="Add numbers",
            replay_policy=replay_policy,
        ),
        add,
    )
    await runtime.initialize()
    await runtime.providers.create(make_config())
    return AgentRunApplication(runtime)
