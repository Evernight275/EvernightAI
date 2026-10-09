from datetime import datetime, timezone

import pytest

from EvernightAI.application.agent import (
    AgentResumeMode,
    agent_resume_mode,
    agent_run_can_resume,
    agent_run_failure,
)
from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.error.skill import SkillConflictError
from EvernightAI.core.schema.agent import (
    AgentPauseCause,
    AgentPauseRequest,
    AgentRunFailure,
    AgentRunHistory,
    AgentRunPause,
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
)


def make_state(**fields: object) -> AgentRunState:
    return AgentRunState.model_validate(
        {
            "run_id": "run-1",
            "request": AgentRunRequest(
                provider_id="provider-1",
                context_id="ctx-1",
                model_id="model-1",
            ),
            **fields,
        }
    )


def pause(*, resumable: bool) -> AgentRunPause:
    return AgentRunPause(
        cause=AgentPauseCause.TIMEOUT,
        checkpoint="chat_completed",
        resumable=resumable,
    )


def test_run_waiting_for_approval_resumes_from_its_pending_tool_calls() -> None:
    state = make_state(status=AgentRunStatus.PAUSED)

    assert state.pause is None
    assert agent_resume_mode(state) is AgentResumeMode.APPROVAL
    assert agent_run_can_resume(state) is True


def test_resumable_pause_continues_from_its_checkpoint() -> None:
    state = make_state(status=AgentRunStatus.PAUSED, pause=pause(resumable=True))

    assert agent_resume_mode(state) is AgentResumeMode.CHECKPOINT
    assert agent_run_can_resume(state) is True


def test_blocked_pause_cannot_resume() -> None:
    state = make_state(status=AgentRunStatus.PAUSED, pause=pause(resumable=False))

    assert agent_run_can_resume(state) is False


@pytest.mark.parametrize(
    ("cause", "trace_name"),
    [
        (AgentPauseCause.MANUAL, "manual_pause"),
        (AgentPauseCause.TIMEOUT, "timeout"),
        (AgentPauseCause.SHUTDOWN, "shutdown"),
        (AgentPauseCause.UNCLEAN_SHUTDOWN, "shutdown"),
        (AgentPauseCause.LEASE_EXPIRED, "lease_expired"),
    ],
)
def test_trace_events_name_both_kinds_of_shutdown_alike(
    cause: AgentPauseCause,
    trace_name: str,
) -> None:
    assert cause.source == trace_name


def test_failure_keeps_detail_only_for_errors_meant_to_show_it() -> None:
    shown = agent_run_failure(
        SkillConflictError("Skill changed", detail="style was updated")
    )
    hidden = agent_run_failure(
        AgentStateError("Broken snapshot", detail="internal state dump")
    )

    assert shown == AgentRunFailure(
        error_type="SkillConflictError",
        message="Skill changed",
        detail="style was updated",
    )
    assert hidden == AgentRunFailure(
        error_type="AgentStateError",
        message="Broken snapshot",
    )
    assert agent_run_failure(ValueError("bad value")) == AgentRunFailure(
        error_type="ValueError",
        message="bad value",
    )


def test_new_snapshot_starts_without_control_state() -> None:
    state = make_state()

    assert state.pause is None
    assert state.pause_request is None
    assert state.failure is None
    assert state.cancel_reason is None
    assert state.history == AgentRunHistory()


def test_snapshot_round_trips_its_control_state() -> None:
    state = make_state(
        status=AgentRunStatus.PAUSED,
        pause=AgentRunPause(
            cause=AgentPauseCause.MANUAL,
            checkpoint="tool_completed",
            resumable=True,
            reason="lunch",
        ),
        pause_request=AgentPauseRequest(reason="later"),
        history=AgentRunHistory(
            started_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            message_offset=4,
            message_indices=[4, 5],
            generation=2,
        ),
        metadata={"request_id": "kept"},
    )

    assert AgentRunState.model_validate_json(state.model_dump_json()) == state


def legacy_state(status: str, runtime: dict[str, object], **metadata: object):
    return make_state(
        status=status,
        metadata={"request_id": "kept", "agent_runtime": runtime, **metadata},
    )


def test_legacy_snapshot_moves_control_state_out_of_metadata() -> None:
    state = legacy_state(
        "failed",
        {
            "history_started_at": "2026-01-02T03:04:05+00:00",
            "context_message_offset": 4,
            "context_message_indices": [4, 5],
            "context_history_generation": 2,
            "tool_rounds_used": 1,
            "pending_approval_count": 0,
            "failure_type": "ProviderUnavailableError",
            "failure_message": "provider chat failed",
            "failure_detail": None,
            "cancel_reason": "operator canceled",
        },
    )

    assert state.metadata == {"request_id": "kept"}
    assert state.history == AgentRunHistory(
        started_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        message_offset=4,
        message_indices=[4, 5],
        generation=2,
    )
    assert state.failure == AgentRunFailure(
        error_type="ProviderUnavailableError",
        message="provider chat failed",
    )
    assert state.cancel_reason == "operator canceled"
    assert state.pause is None


@pytest.mark.parametrize(
    ("runtime", "top_level", "expected"),
    [
        (
            {
                "manual_pause": True,
                "pause_source": "manual_pause",
                "pause_checkpoint": "tool_completed",
                "pause_reason": "lunch",
                "recovery_eligible": True,
            },
            {},
            AgentRunPause(
                cause=AgentPauseCause.MANUAL,
                checkpoint="tool_completed",
                resumable=True,
                reason="lunch",
            ),
        ),
        (
            {
                "manual_pause": False,
                "pause_source": "lease_expired",
                "pause_checkpoint": "tool_execution_incomplete",
                "recovery_eligible": False,
            },
            {"interrupted": True, "interruption_reason": "runtime_restart"},
            AgentRunPause(
                cause=AgentPauseCause.LEASE_EXPIRED,
                checkpoint="tool_execution_incomplete",
                resumable=False,
            ),
        ),
        (
            {
                "manual_pause": True,
                "pause_source": "shutdown",
                "pause_checkpoint": "run_started",
                "recovery_eligible": True,
            },
            {"interrupted": True, "interruption_reason": "runtime_restart"},
            AgentRunPause(
                cause=AgentPauseCause.UNCLEAN_SHUTDOWN,
                checkpoint="run_started",
                resumable=True,
            ),
        ),
        (
            {
                "manual_pause": True,
                "pause_source": "shutdown",
                "pause_checkpoint": "run_started",
                "shutdown_reason": "shutdown",
                "recovery_eligible": True,
            },
            {},
            AgentRunPause(
                cause=AgentPauseCause.SHUTDOWN,
                checkpoint="run_started",
                resumable=True,
            ),
        ),
    ],
)
def test_legacy_paused_snapshot_keeps_its_cause_checkpoint_and_resumability(
    runtime: dict[str, object],
    top_level: dict[str, object],
    expected: AgentRunPause,
) -> None:
    state = legacy_state("paused", runtime, **top_level)

    assert state.pause == expected
    assert state.metadata == {"request_id": "kept"}


def test_legacy_approval_pause_has_no_checkpoint_pause() -> None:
    # A resumed manual pause left these flags behind before the next approval.
    state = legacy_state(
        "paused",
        {
            "manual_pause": False,
            "pause_requested": False,
            "pause_source": "manual_pause",
            "pause_checkpoint": "tool_completed",
            "recovery_eligible": True,
        },
    )

    assert state.pause is None
    assert state.pause_request is None
    assert agent_resume_mode(state) is AgentResumeMode.APPROVAL


def test_legacy_pause_flags_do_not_pause_a_run_that_is_no_longer_paused() -> None:
    state = legacy_state(
        "finished",
        {"manual_pause": True, "pause_source": "timeout", "recovery_eligible": True},
    )

    assert state.pause is None


def test_legacy_running_snapshot_keeps_a_pending_pause_request() -> None:
    state = legacy_state(
        "running",
        {"pause_requested": True, "pause_reason": "operator paused"},
    )

    assert state.pause_request == AgentPauseRequest(reason="operator paused")


def test_new_fields_win_over_legacy_metadata_in_the_same_snapshot() -> None:
    state = make_state(
        status="paused",
        pause=pause(resumable=False),
        metadata={"agent_runtime": {"manual_pause": True}},
    )

    assert state.pause == pause(resumable=False)
    assert state.metadata == {}


def test_legacy_recovery_denial_wins_over_checkpoint_resume_flag() -> None:
    state = legacy_state(
        "paused",
        {
            "manual_pause": True,
            "recovery_eligible": False,
            "pause_source": "lease_expired",
            "pause_checkpoint": "tool_execution_incomplete",
        },
    )

    assert state.pause is not None
    assert state.pause.resumable is False
    assert agent_run_can_resume(state) is False


@pytest.mark.parametrize("source", [["unexpected"], {"source": "unexpected"}])
def test_legacy_non_text_pause_source_keeps_its_resume_behavior(source: object) -> None:
    state = legacy_state(
        "paused",
        {"manual_pause": True, "recovery_eligible": True, "pause_source": source},
    )

    assert state.pause is not None
    assert state.pause.cause is AgentPauseCause.MANUAL
    assert agent_run_can_resume(state) is True
