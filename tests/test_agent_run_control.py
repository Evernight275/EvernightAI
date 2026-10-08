import pytest

from EvernightAI.application.agent import (
    AgentPauseCause,
    AgentResumeMode,
    AgentRunControl,
    AgentRunPause,
)
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunState


def state_with(metadata: dict[str, object]) -> AgentRunState:
    return AgentRunState(
        run_id="run-1",
        request=AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
        ),
        metadata=metadata,
    )


@pytest.mark.parametrize(
    ("cause", "source"),
    [
        (AgentPauseCause.MANUAL, "manual_pause"),
        (AgentPauseCause.TIMEOUT, "timeout"),
        (AgentPauseCause.SHUTDOWN, "shutdown"),
        (AgentPauseCause.UNCLEAN_SHUTDOWN, "shutdown"),
        (AgentPauseCause.LEASE_EXPIRED, "lease_expired"),
    ],
)
@pytest.mark.parametrize("resumable", [True, False])
def test_pause_records_its_cause_checkpoint_and_whether_it_can_resume(
    cause: AgentPauseCause,
    source: str,
    resumable: bool,
) -> None:
    pause = AgentRunPause(cause=cause, checkpoint="chat_completed", resumable=resumable)

    control = AgentRunControl.from_state(state_with(pause.apply({"kept": True})))

    assert control.source == source
    assert control.checkpoint == "chat_completed"
    assert control.recoverable is resumable
    assert control.resume_mode is (
        AgentResumeMode.CHECKPOINT if resumable else AgentResumeMode.APPROVAL
    )


def test_pause_keeps_unrelated_metadata_and_does_not_mutate_its_input() -> None:
    metadata: dict[str, object] = {
        "kept": True,
        "agent_runtime": {"context_message_offset": 3},
    }

    paused = AgentRunPause(
        cause=AgentPauseCause.TIMEOUT,
        checkpoint="run_started",
        resumable=True,
    ).apply(metadata)

    assert paused["kept"] is True
    assert paused["agent_runtime"]["context_message_offset"] == 3  # type: ignore[index]
    assert metadata == {"kept": True, "agent_runtime": {"context_message_offset": 3}}


def test_manual_pause_consumes_the_request_that_asked_for_it() -> None:
    requested = AgentRunControl.request_pause({}, "lunch")
    assert AgentRunControl.from_state(state_with(requested)).pause_requested is True
    assert AgentRunControl.from_state(state_with(requested)).pause_reason == "lunch"

    paused = AgentRunPause(
        cause=AgentPauseCause.MANUAL,
        checkpoint="tool_completed",
        resumable=True,
        reason="lunch",
    ).apply(requested)
    control = AgentRunControl.from_state(state_with(paused))

    assert control.pause_requested is False
    assert control.pause_reason == "lunch"


def test_resuming_clears_the_pause_but_keeps_its_history() -> None:
    paused = AgentRunPause(
        cause=AgentPauseCause.MANUAL,
        checkpoint="tool_completed",
        resumable=True,
    ).apply({})

    control = AgentRunControl.from_state(state_with(AgentRunControl.resumed(paused)))

    assert control.resume_mode is AgentResumeMode.APPROVAL
    assert control.pause_requested is False
    assert control.checkpoint == "tool_completed"
    assert control.source == "manual_pause"


@pytest.mark.parametrize("resumable", [True, False])
def test_operator_resolution_decides_whether_a_blocked_pause_can_resume(
    resumable: bool,
) -> None:
    blocked = AgentRunPause(
        cause=AgentPauseCause.LEASE_EXPIRED,
        checkpoint="tool_execution_incomplete",
        resumable=False,
    ).apply({})

    control = AgentRunControl.from_state(
        state_with(AgentRunControl.resolved_by_operator(blocked, resumable=resumable))
    )

    assert control.recoverable is resumable
    assert control.checkpoint == "operator_resolution"
    assert control.source == "lease_expired"
