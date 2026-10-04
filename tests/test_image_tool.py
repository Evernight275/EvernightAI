import asyncio
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from EvernightAI.application.agent import AgentRunApplication
from EvernightAI.application.image import ImageApplication
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime, create_runtime
from EvernightAI.core.error.tool import ToolExecutionError, ToolPolicyError
from EvernightAI.core.error.provider import ProviderRequestTimeoutError
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunStatus
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.content import (
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.image import ImageEditRequest, ImageGenerationRequest
from EvernightAI.core.schema.image_task import ImageTask
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelConfig,
    ProviderType,
    ProviderModelCapability,
)
from EvernightAI.core.schema.session import Session
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolApprovalStatus,
    ToolCall,
    ToolReplayPolicy,
)
from tests.test_image_editing import EditProvider
from tests.test_image_generation import PNG


def message(text: str) -> Content:
    return Content(
        role=MessageRole.USER,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


async def configure(runtime, provider):
    async def build(_config):
        return provider

    runtime.provider_factory.register(ProviderType.OPENAI, build)
    await runtime.providers.create(
        ProviderConfig(
            provider_id="main",
            name="Main",
            type=ProviderType.OPENAI,
            model={
                "image": ProviderModelConfig(
                    model_id="image-model",
                    capabilities=[ProviderModelCapability.IMAGE_GENERATION],
                )
            },
        )
    )
    return create_interface(runtime)


class ChatImageProvider(EditProvider):
    def __init__(self):
        super().__init__()
        self.chat_requests = []

    async def chat(self, request):
        self.chat_requests.append(request)
        if request.messages[-1].role is MessageRole.TOOL:
            return ChatResponse(
                model_id=request.model_id,
                message=Content(
                    role=MessageRole.ASSISTANT,
                    content=[
                        ContentPart(
                            type=ContentPartType.TEXT, text="图片已完成，可以继续修改。"
                        )
                    ],
                ),
            )
        previous = [
            part.text
            for item in request.messages
            if item.role is MessageRole.TOOL
            for part in item.content or []
            if part.text
        ]
        current_content = request.messages[-1].content
        assert current_content
        args = {
            "prompt": current_content[0].text,
            "_execution_context": {"owner_id": "bob", "session_id": "bob-session"},
        }
        if previous:
            result = json.loads(previous[-1])
            result = result.get("tool_call_result", result)
            args["references"] = [{"record_id": result["record_id"]}]
            args["timeout_seconds"] = 420
            args["quality"] = "low"
            args["output_format"] = "webp"
        return ChatResponse(
            model_id=request.model_id,
            message=Content(
                role=MessageRole.ASSISTANT,
                tool_calls=[
                    ToolCall(
                        tool_call_id=f"image-call-{len(self.chat_requests)}",
                        tool_call={"name": "generate_image", "arguments": args},
                        metadata={
                            "owner_id": "bob",
                            "session_id": "bob-session",
                            "run_id": "spoof",
                            "approved": True,
                        },
                    )
                ],
            ),
        )

    async def supports(self, capability):
        return True


@pytest.mark.asyncio
async def test_agent_image_tool_approval_generation_editing_ownership_and_slim_context(
    tmp_path: Path,
):
    runtime = create_sqlite_runtime(tmp_path / "runtime.sqlite3")
    provider = ChatImageProvider()
    interface = await configure(runtime, provider)
    scope = PrincipalScope(owner_id="alice")
    await runtime.contexts.create(
        Context(context_id="ctx", owner_id="alice"), principal_scope=scope
    )
    await runtime.sessions.create(
        Session(session_id="session", context_id="ctx", owner_id="alice"),
        principal_scope=scope,
    )
    app = AgentRunApplication(runtime)
    results = []
    try:
        for index, prompt in enumerate(["画一片绿色叶子", "把刚才的叶子改成蓝色"]):
            request = AgentRunRequest(
                provider_id="main",
                model_id="chat-model",
                context_id="ctx",
                owner_id="alice",
                messages=[message(prompt)],
                tools=interface.tools.list_tools(),
                pause_on_approval=True,
                metadata={"run_id": f"image-run-{index}", "session_id": "session"},
            )
            state = await app.start(request, principal_scope=scope)
            assert state.status is AgentRunStatus.PAUSED
            assert len(provider.requests) == index, (
                "unapproved image tools must not call the image provider"
            )
            approval = state.pending_approval_requests[0]
            state = await app.resume(
                state.run_id,
                [
                    ToolApprovalDecision(
                        approval_id=approval.approval_id,
                        tool_call_id=approval.tool_call_id,
                        status=ToolApprovalStatus.APPROVED,
                    )
                ],
                principal_scope=scope,
            )
            assert state.status is AgentRunStatus.FINISHED
            outputs = [
                step.tool_result.tool_call_result
                for step in state.steps
                if step.tool_result
            ]
            result = outputs[-1]
            results.append(result)
            record = ImageApplication(runtime).get_record(
                result["record_id"], principal_scope=scope
            )
            assert record.owner_id == "alice"
            assert runtime.image_tasks.get(result["task_id"]).session_id == "session"
            assert len(provider.requests) == index + 1
            assert provider.requests[-1].timeout_seconds == (180 if index == 0 else 420)
            assert provider.requests[-1].quality == ("high" if index == 0 else "low")
            assert provider.requests[-1].output_format == (
                "png" if index == 0 else "webp"
            )
            assert "base64_data" not in json.dumps(result)
            assert PNG not in json.dumps(result)
        assert isinstance(provider.requests[1], ImageEditRequest)
        assert provider.requests[1].images[0].base64_data == PNG
        assert results[0]["record_id"] != results[1]["record_id"]
        assert any(
            '"record_id"' in (part.text or "")
            for req in provider.chat_requests
            for item in req.messages
            if item.role is MessageRole.TOOL
            for part in item.content or []
        )
        assert not any(
            PNG in (part.text or "")
            for req in provider.chat_requests
            for item in req.messages
            for part in item.content or []
        )
    finally:
        await app.close()
        await runtime.close()


@pytest.mark.asyncio
async def test_image_tool_timeout_reason_is_persisted_in_agent_execution(
    tmp_path: Path,
):
    class TimeoutProvider(ChatImageProvider):
        async def generate_images(self, request):
            self.requests.append(request)
            raise ProviderRequestTimeoutError("Request timed out.")

    runtime = create_sqlite_runtime(tmp_path / "runtime.sqlite3")
    provider = TimeoutProvider()
    interface = await configure(runtime, provider)
    await runtime.contexts.create(Context(context_id="ctx"))
    app = AgentRunApplication(runtime)
    try:
        state = await app.start(
            AgentRunRequest(
                provider_id="main",
                model_id="chat-model",
                context_id="ctx",
                messages=[message("Draw a leaf")],
                tools=interface.tools.list_tools(),
                pause_on_approval=True,
                metadata={"run_id": "timeout-run"},
            )
        )
        approval = state.pending_approval_requests[0]
        state = await app.resume(
            state.run_id,
            [
                ToolApprovalDecision(
                    approval_id=approval.approval_id,
                    tool_call_id=approval.tool_call_id,
                    status=ToolApprovalStatus.APPROVED,
                )
            ],
        )
        expected = (
            "The tool generate_image execution failed: "
            "Image task failed (ProviderRequestTimeoutError): Request timed out."
        )
        failures = [event for event in state.trace if event.error_type]
        assert failures and all(event.error_message == expected for event in failures)
        assert runtime.tool_execution_register is not None
        attempts = runtime.tool_execution_register.list_attempts(state.run_id)
        assert len(attempts) == 1
        assert attempts[0].error_message == expected
        assert len(provider.requests) == 1
        assert provider.requests[0].timeout_seconds == 180
        with pytest.raises(ToolExecutionError, match="ProviderRequestTimeoutError"):
            await runtime.tools.execute(attempts[0].tool_call)
        assert len(provider.requests) == 1
    finally:
        await app.close()
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [None, 60])
async def test_existing_image_task_keeps_original_defaults_on_replay(
    tmp_path: Path, timeout
):
    runtime = create_sqlite_runtime(tmp_path / "runtime.sqlite3")
    provider = EditProvider()
    await configure(runtime, provider)
    task_id = uuid5(NAMESPACE_URL, "EvernightAI:image-tool:None:legacy-run:call").hex
    runtime.image_tasks.create(
        ImageTask(
            task_id=task_id,
            provider_id="main",
            request=ImageGenerationRequest(
                model_id="image-model", prompt="Leaf", timeout_seconds=timeout
            ),
            status="failed",
            error_type="ProviderRequestTimeoutError",
            error_message="Request timed out.",
        )
    )
    call = ToolCall(
        tool_call_id="call",
        tool_call={"name": "generate_image", "arguments": {"prompt": "Leaf"}},
        metadata={"approved": True, "run_id": "legacy-run"},
    )
    try:
        with pytest.raises(ToolExecutionError, match="ProviderRequestTimeoutError"):
            await runtime.tools.execute(call)
        assert runtime.image_tasks.get(task_id).request.timeout_seconds == timeout
        assert runtime.image_tasks.get(task_id).request.quality is None
        assert runtime.image_tasks.get(task_id).request.output_format is None
        assert not provider.requests
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_image_tool_idempotence_cancellation_and_cross_owner_reference_rejection():
    runtime = create_runtime()
    provider = EditProvider(blocked=True)
    await configure(runtime, provider)
    tool = runtime.tool_register.get("generate_image")
    assert tool.replay_policy is ToolReplayPolicy.IDEMPOTENT
    call = ToolCall(
        tool_call_id="call",
        tool_call={"name": "generate_image", "arguments": {"prompt": "Leaf"}},
        metadata={"approved": True, "owner_id": "alice", "run_id": "run"},
    )
    try:
        first = asyncio.create_task(runtime.tools.execute(call))
        await asyncio.wait_for(provider.started.wait(), 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        provider.release.set()
        result = await runtime.tools.execute(call)
        await runtime.providers.delete("main")
        repeated = await runtime.tools.execute(call)
        assert result.tool_call_result == repeated.tool_call_result
        assert len(provider.requests) == 1
        forbidden = ToolCall(
            tool_call_id="edit",
            tool_call={
                "name": "generate_image",
                "arguments": {
                    "prompt": "Edit",
                    "references": [{"record_id": result.tool_call_result["record_id"]}],
                },
            },
            metadata={"approved": True, "owner_id": "bob"},
        )
        with pytest.raises(ToolExecutionError):
            await runtime.tools.execute(forbidden)
        assert len(provider.requests) == 1
        unapproved = call.model_copy(update={"metadata": {"owner_id": "alice"}})
        with pytest.raises(ToolPolicyError):
            await runtime.tools.execute(unapproved)
        assert len(provider.requests) == 1
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_missing_model_and_unknown_arguments_do_not_make_paid_calls():
    runtime = create_runtime()
    create_interface(runtime)
    try:
        for args in [
            {"prompt": "Leaf"},
            {"prompt": "Leaf", "owner_id": "bob"},
            {"prompt": "Leaf", "timeout_seconds": 0},
            {"prompt": "Leaf", "timeout_seconds": 601},
        ]:
            call = ToolCall(
                tool_call_id="call",
                tool_call={"name": "generate_image", "arguments": args},
                metadata={"approved": True},
            )
            with pytest.raises(ToolExecutionError):
                await runtime.tools.execute(call)
        assert runtime.image_tasks.list_tasks(limit=20) == []
    finally:
        await runtime.close()
