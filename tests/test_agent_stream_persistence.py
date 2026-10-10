from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
import subprocess
import sys
from typing import cast

import pytest

from EvernightAI.application.agent import (
    AgentRunApplication,
    recover_interrupted_agent_runs,
)
from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.error.provider import ProviderResponseError
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
    AgentTraceEvent,
    AgentTraceEventType,
)
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.content import ChatRequest
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.infra.adapters.agent.sqlite import (
    SQLiteAgentRunStateRegister,
    SQLiteAgentTraceRegister,
)
from tests.test_application_agent import (
    FinalAnswerProvider,
    make_config,
    make_message,
    make_runtime,
)


class TextStreamProvider(FinalAnswerProvider):
    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.fail = fail

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        self.requests.append(request)
        return self._events()

    async def _events(self) -> AsyncIterator[ChatStreamEvent]:
        for text in ["one", "two", "three"]:
            yield ChatStreamEvent(
                event_type=ChatStreamEventType.MESSAGE_DELTA,
                text_delta=text,
            )
        if self.fail:
            raise ProviderResponseError("stream interrupted")
        yield ChatStreamEvent(event_type=ChatStreamEventType.DONE)


def text_deltas(state: AgentRunState) -> list[str | None]:
    return [
        event.text_delta
        for event in state.trace
        if event.event_type is AgentTraceEventType.CHAT_DELTA
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["complete", "pause", "cancel", "fail"])
async def test_stream_journals_text_before_delivery_and_preserves_controls(
    tmp_path: Path, control: str
) -> None:
    database = tmp_path / "agent.sqlite3"
    states = SQLiteAgentRunStateRegister(database)
    traces = SQLiteAgentTraceRegister(database)
    provider = TextStreamProvider(fail=control == "fail")
    runtime = make_runtime(
        provider=provider,
        agent_state_register=states,
        agent_trace_register=traces,
    )
    app = AgentRunApplication(runtime)
    iterator: AsyncGenerator[AgentTraceEvent, None] | None = None
    try:
        await runtime.contexts.create(Context(context_id="ctx-1"))
        await runtime.providers.create(make_config())
        iterator = cast(
            AsyncGenerator[AgentTraceEvent, None],
            app.start_stream(
                AgentRunRequest(
                    provider_id="provider-1",
                    context_id="ctx-1",
                    model_id="model-1",
                    messages=[make_message("Hello")],
                    metadata={"run_id": "stream", "stream": True},
                )
            ).__aiter__(),
        )
        assert (await anext(iterator)).event_type is AgentTraceEventType.RUN_STARTED
        checkpoint = states.get_state("stream")
        assert (await anext(iterator)).text_delta == "one"
        assert states.get_state("stream").applied_trace_sequence == (
            checkpoint.applied_trace_sequence
        )
        assert text_deltas(states.get_state("stream")) == []
        reader = SQLiteAgentTraceRegister(database)
        try:
            assert reader.list_events("stream")[-1].text_delta == "one"
        finally:
            reader.close()
        assert text_deltas(app.get_state("stream")) == ["one"]
        assert text_deltas(app.list_states(status=AgentRunStatus.RUNNING)[0]) == ["one"]

        if control == "pause":
            await app.pause("stream", reason="operator pause")
        assert (await anext(iterator)).text_delta == "two"
        assert text_deltas(app.get_state("stream")) == ["one", "two"]
        assert text_deltas(app.get_state("stream")) == ["one", "two"]
        if control == "pause":
            assert states.get_state("stream").pause_request is not None
        if control == "cancel":
            await app.cancel("stream", reason="operator cancel")

        if control == "fail":
            with pytest.raises(ProviderResponseError, match="stream interrupted"):
                _ = [event async for event in iterator]
        else:
            _ = [event async for event in iterator]
        final = app.get_state("stream")
        assert (
            final.status
            is {
                "complete": AgentRunStatus.FINISHED,
                "pause": AgentRunStatus.PAUSED,
                "cancel": AgentRunStatus.CANCELED,
                "fail": AgentRunStatus.FAILED,
            }[control]
        )
        assert text_deltas(final) == (
            ["one", "two"] if control == "cancel" else ["one", "two", "three"]
        )
        assert final.trace == traces.list_events("stream")
        if control == "pause":
            assert final.pause is not None
            assert final.pause.checkpoint == "chat_completed"
            assert final.pause.reason == "operator pause"
            assert (await app.resume("stream", [])).status is AgentRunStatus.FINISHED
            assert len(provider.requests) == 1
    finally:
        if iterator is not None:
            await iterator.aclose()
        await app.close()
        await runtime.close()


def test_status_query_observes_external_controls_and_enforces_scope(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agent.sqlite3"
    states = SQLiteAgentRunStateRegister(database)
    writer = SQLiteAgentRunStateRegister(database)
    traces = SQLiteAgentTraceRegister(database)
    owner = PrincipalScope(owner_id="alice")
    other = PrincipalScope(owner_id="bob")
    state = AgentRunState(
        run_id="owned",
        owner_id="alice",
        request=AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            owner_id="alice",
        ),
    )
    try:
        states.create_state(state, principal_scope=owner)
        assert (
            states.get_status("owned", principal_scope=owner) is AgentRunStatus.RUNNING
        )
        state.status = AgentRunStatus.CANCELED
        writer.save_state(state, principal_scope=owner)
        assert (
            states.get_status("owned", principal_scope=owner) is AgentRunStatus.CANCELED
        )
        with pytest.raises(AgentStateError):
            states.get_status("owned", principal_scope=other)
        with pytest.raises(AgentStateError):
            states.get_status("missing", principal_scope=owner)
        app = AgentRunApplication(
            make_runtime(
                agent_state_register=states,
                agent_trace_register=traces,
            )
        )
        with pytest.raises(AgentStateError):
            app.list_trace("owned", principal_scope=other)
        assert app.list_trace("owned", principal_scope=owner) == []
        state.status = AgentRunStatus.RUNNING
        writer.save_state(state, principal_scope=owner)
        traces.append_event(
            "owned",
            AgentTraceEvent(
                event_type=AgentTraceEventType.CHAT_DELTA, text_delta="private"
            ),
        )
        assert text_deltas(app.get_state("owned", principal_scope=owner)) == ["private"]
        with pytest.raises(AgentStateError):
            app.get_state("owned", principal_scope=other)
        assert app.list_states(principal_scope=other) == []
    finally:
        writer.close()
        states.close()
        traces.close()


@pytest.mark.asyncio
async def test_text_deltas_do_not_read_or_rewrite_full_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "agent.sqlite3"
    states = SQLiteAgentRunStateRegister(database)
    traces = SQLiteAgentTraceRegister(database)
    runtime = make_runtime(agent_state_register=states, agent_trace_register=traces)
    app = AgentRunApplication(runtime)
    state = AgentRunState(
        run_id="deltas",
        request=AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
        ),
    )
    states.create_state(state)

    async def events() -> AsyncIterator[AgentTraceEvent]:
        for _ in range(100):
            yield app._agent._add_trace(
                state,
                AgentTraceEvent(
                    event_type=AgentTraceEventType.CHAT_DELTA, text_delta="x"
                ),
            )

    def forbid_snapshot(*args: object, **kwargs: object) -> None:
        pytest.fail("Text deltas must not read or rewrite the growing full snapshot")

    iterator = cast(
        AsyncGenerator[AgentTraceEvent, None], app._stream_and_store(events(), state)
    )
    try:
        with monkeypatch.context() as patch:
            patch.setattr(states, "get_state", forbid_snapshot)
            patch.setattr(states, "save_state", forbid_snapshot)
            for sequence in range(1, 101):
                assert (await anext(iterator)).sequence == sequence
        assert text_deltas(states.get_state("deltas")) == []
        assert len(app.list_trace("deltas")) == 100
    finally:
        await iterator.aclose()
        await runtime.close()


CRASH_SCRIPT = """
import asyncio
import os
import sys
from EvernightAI.application.agent import AgentRunApplication
from EvernightAI.core.schema.agent import AgentRunRequest, AgentTraceEventType
from EvernightAI.core.schema.context import Context
from EvernightAI.infra.adapters.agent.sqlite import (
    SQLiteAgentRunStateRegister, SQLiteAgentTraceRegister,
)
from tests.test_agent_stream_persistence import TextStreamProvider
from tests.test_application_agent import make_config, make_message, make_runtime

async def main():
    runtime = make_runtime(
        provider=TextStreamProvider(),
        agent_state_register=SQLiteAgentRunStateRegister(sys.argv[1]),
        agent_trace_register=SQLiteAgentTraceRegister(sys.argv[1]),
    )
    await runtime.contexts.create(Context(context_id='ctx-1'))
    await runtime.providers.create(make_config())
    request = AgentRunRequest(
        provider_id='provider-1', context_id='ctx-1', model_id='model-1',
        messages=[make_message('Hello')],
        metadata={'run_id': 'crashed', 'stream': True},
    )
    app = AgentRunApplication(runtime)
    async for event in app.start_stream(request):
        if event.event_type is AgentTraceEventType.CHAT_DELTA:
            if sys.argv[2] == 'pause':
                await app.pause('crashed')
            os._exit(70)

asyncio.run(main())
"""


@pytest.mark.parametrize("control", ["none", "pause"])
def test_process_crash_after_text_delivery_recovers_journal_tail(
    tmp_path: Path,
    control: str,
) -> None:
    database = tmp_path / "agent.sqlite3"
    crashed = subprocess.run(
        [sys.executable, "-c", CRASH_SCRIPT, str(database), control],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert crashed.returncode == 70, crashed.stderr
    states = SQLiteAgentRunStateRegister(database)
    traces = SQLiteAgentTraceRegister(database)
    try:
        snapshot = states.get_state("crashed")
        assert text_deltas(snapshot) == (["one"] if control == "pause" else [])
        assert snapshot.applied_trace_sequence == 1
        assert traces.list_events("crashed")[-1].text_delta == "one"
        assert recover_interrupted_agent_runs(states, traces) == 1
        recovered = states.get_state("crashed")
        assert recovered.status is AgentRunStatus.PAUSED
        assert text_deltas(recovered) == ["one"]
        assert recovered.trace == traces.list_events("crashed")
        assert recovered.pause is not None
        assert recovered.pause.resumable
        assert recovered.response is None
        assert recover_interrupted_agent_runs(states, traces) == 0
    finally:
        states.close()
        traces.close()
