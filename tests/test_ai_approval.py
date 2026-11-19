import asyncio
import json

import pytest

from EvernightAI.application.agent import AgentRunApplication
from EvernightAI.application.agent_recovery import inspect_agent_run_checkpoint
from EvernightAI.application.ai_approval import SYSTEM_PROMPT
from EvernightAI.bootstrap.config import create_runtime_from_config
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunStatus,
    AgentStepType,
    AgentTraceEventType,
)
from EvernightAI.core.schema.content import (
    ChatResponse,
    ChatUsage,
    Content,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolApprovalStatus,
    ToolCall,
)
from EvernightAI.infra.registrations.tool.restricted_shell import (
    register_restricted_shell_tool,
)
from EvernightAI.interface.cli.schema import EvernightConfig
from tests.fakes.agent import InMemoryAgentRunStateRegister, InMemoryAgentTraceRegister
from tests.test_application_agent import (
    ToolCallingProvider,
    make_config,
    make_message,
    make_response,
    make_runtime,
)


class ApprovalProvider(ToolCallingProvider):
    def __init__(self, reply="approve", command="echo reviewed > result.txt"):
        super().__init__()
        self.reply = reply
        self.command = command
        self.reviews = []
        self.main_calls = 0
        self.tool_rounds = 1

    async def chat(self, request):
        self.requests.append(request)
        first = request.messages[0].content or []
        if first and first[0].text == SYSTEM_PROMPT:
            self.reviews.append(request)
            if self.reply == "error":
                raise RuntimeError("provider unavailable")
            if self.reply == "timeout":
                await asyncio.Event().wait()
            text = (
                "not json"
                if self.reply == "malformed"
                else json.dumps(
                    {
                        "decision": "approve"
                        if self.reply in {"approve", "medium"}
                        else "human",
                        "risk": "medium" if self.reply == "medium" else "low",
                        "reason": "Reviewed for the requested task",
                    }
                )
            )
            return make_response(text).model_copy(
                update={"usage": ChatUsage(total_tokens=5)}
            )
        self.main_calls += 1
        if self.main_calls <= self.tool_rounds:
            return ChatResponse(
                model_id=request.model_id,
                message=Content(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            tool_call_id="shell-1",
                            tool_call={
                                "name": "restricted_shell",
                                "arguments": {"command": self.command},
                            },
                        )
                    ],
                ),
                finish_reason="tool_calls",
                usage=ChatUsage(total_tokens=10),
            )
        return make_response("Done").model_copy(
            update={"usage": ChatUsage(total_tokens=10)}
        )


async def setup_run(
    tmp_path,
    *,
    reply="approve",
    command="echo reviewed > result.txt",
    enabled=True,
    blocked=None,
):
    provider = ApprovalProvider(reply, command)
    runtime = make_runtime(
        provider, InMemoryAgentRunStateRegister(), InMemoryAgentTraceRegister()
    )
    runtime.ai_approval.enabled = enabled
    runtime.ai_approval.timeout_seconds = 0.02
    register_restricted_shell_tool(
        runtime.tool_register,
        allowed_commands=set(),
        working_directory=tmp_path,
        blocked_commands=blocked,
        requires_approval=True,
    )
    await runtime.providers.create(make_config())
    await runtime.contexts.create(Context(context_id="ctx-1"))
    app = AgentRunApplication(runtime)
    request = AgentRunRequest(
        provider_id="provider-1",
        context_id="ctx-1",
        model_id="model-1",
        messages=[make_message("Write reviewed to result.txt")],
        tools=runtime.tools.list_tools(),
    )
    return runtime, provider, app, request


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_low_risk_review_executes_and_accounts_for_usage(tmp_path, stream):
    runtime, provider, app, request = await setup_run(tmp_path)
    try:
        if stream:
            request.metadata["run_id"] = "stream-review"
            events = [event async for event in app.start_stream(request)]
            assert any(
                event.event_type is AgentTraceEventType.AI_APPROVAL_REVIEWED
                for event in events
            )
            state = app.get_state("stream-review")
        else:
            state = await app.start(request)
        assert state.status is AgentRunStatus.FINISHED
        assert (tmp_path / "result.txt").read_text() == "reviewed\n"
        assert len(provider.reviews) == 1
        assert provider.reviews[0].tools is None
        assert provider.reviews[0].prompt_cache is None
        assert state.usage is not None
        assert state.usage.total_tokens == 25
        assert sum(step.step_type is AgentStepType.CHAT for step in state.steps) == 2
        review = next(
            event
            for event in state.trace
            if event.event_type is AgentTraceEventType.AI_APPROVAL_REVIEWED
        )
        assert review.metadata["decision"] == "approve"
        approval = next(
            event
            for event in state.trace
            if event.event_type is AgentTraceEventType.TOOL_APPROVAL_DECIDED
        )
        assert approval.approval_decision is not None
        assert approval.approval_decision.status is ToolApprovalStatus.APPROVED
        assert not state.request.tool_approvals
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["human", "medium", "malformed", "error", "timeout"])
async def test_uncertain_review_pauses_and_human_can_resume(tmp_path, reply):
    runtime, provider, app, request = await setup_run(tmp_path, reply=reply)
    try:
        state = await app.start(request)
        assert state.status is AgentRunStatus.PAUSED
        assert not (tmp_path / "result.txt").exists()
        pending = state.pending_approval_requests[0]
        assert "ai_review" in pending.metadata
        state = await app.resume(
            state.run_id,
            [
                ToolApprovalDecision(
                    approval_id=pending.approval_id,
                    tool_call_id=pending.tool_call_id,
                    status=ToolApprovalStatus.APPROVED,
                )
            ],
        )
        assert state.status is AgentRunStatus.FINISHED
        assert (tmp_path / "result.txt").read_text() == "reviewed\n"
        assert len(provider.reviews) == 1
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["disabled", "hard_block", "safe_without_approval"])
async def test_review_only_runs_for_pending_approvals(tmp_path, mode):
    runtime, provider, app, request = await setup_run(
        tmp_path,
        enabled=mode != "disabled",
        blocked={"echo"} if mode == "hard_block" else None,
    )
    if mode == "safe_without_approval":
        register_restricted_shell_tool(
            runtime.tool_register,
            allowed_commands=set(),
            working_directory=tmp_path,
            requires_approval=False,
        )
        provider.command = "echo safe"
    try:
        state = await app.start(request)
        assert not provider.reviews
        assert state.status is (
            AgentRunStatus.PAUSED if mode == "disabled" else AgentRunStatus.FINISHED
        )
        assert not (tmp_path / "result.txt").exists()
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_policy_is_rechecked_after_ai_review(tmp_path):
    runtime, provider, app, request = await setup_run(tmp_path)
    original = provider.chat

    async def chat_then_block(request):
        result = await original(request)
        if provider.reviews:
            register_restricted_shell_tool(
                runtime.tool_register,
                allowed_commands=set(),
                working_directory=tmp_path,
                blocked_commands={"echo"},
            )
        return result

    provider.chat = chat_then_block
    try:
        await app.start(request)
        assert not (tmp_path / "result.txt").exists()
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_ai_config_is_composed_without_initializing_storage(tmp_path):
    database = tmp_path / "runtime.sqlite3"
    config = EvernightConfig.model_validate(
        {
            "runtime": {"database_path": str(database)},
            "ai_approval": {
                "enabled": True,
                "provider_id": "reviewer",
                "model_id": "review-model",
            },
        }
    )
    runtime = create_runtime_from_config(config)
    try:
        assert runtime.ai_approval == config.ai_approval
        assert not database.exists()
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_repeated_call_id_is_reviewed_again_in_each_round(tmp_path):
    runtime, provider, app, request = await setup_run(tmp_path)
    provider.tool_rounds = 2
    request.max_tool_rounds = 2
    try:
        state = await app.start(request)
        assert state.status is AgentRunStatus.FINISHED
        assert len(provider.reviews) == 2
        assert not state.request.tool_approvals
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_explicit_human_denial_does_not_trigger_review(tmp_path):
    runtime, provider, app, request = await setup_run(tmp_path)
    request.tool_approvals = [
        ToolApprovalDecision(
            approval_id="shell-1:approval",
            tool_call_id="shell-1",
            status=ToolApprovalStatus.DENIED,
        )
    ]
    try:
        await app.start(request)
        assert not provider.reviews
        assert not (tmp_path / "result.txt").exists()
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_recovery_restores_review_usage_once_without_granting_approval(tmp_path):
    runtime, provider, app, request = await setup_run(tmp_path, reply="human")
    try:
        state = await app.start(request)
        snapshot = state.model_copy(deep=True)
        chat = next(
            event
            for event in snapshot.trace
            if event.event_type is AgentTraceEventType.CHAT_COMPLETED
        )
        snapshot.steps = [
            step
            for step in snapshot.steps
            if step.step_type is not AgentStepType.APPROVAL
        ]
        snapshot.trace = [
            event
            for event in snapshot.trace
            if (event.sequence or 0) <= (chat.sequence or 0)
        ]
        snapshot.applied_trace_sequence = chat.sequence
        snapshot.pending_approval_requests = []
        for _ in range(2):
            assert inspect_agent_run_checkpoint(snapshot, state.trace).eligible
            assert (
                sum(step.step_type is AgentStepType.APPROVAL for step in snapshot.steps)
                == 1
            )
            assert snapshot.usage is not None
            assert snapshot.usage.total_tokens == 15
            assert snapshot.pending_approval_requests
            assert not snapshot.request.tool_approvals
    finally:
        await runtime.close()
