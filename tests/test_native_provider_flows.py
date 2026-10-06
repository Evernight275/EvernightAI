import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from EvernightAI.application.agent import AgentRunApplication
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.error.provider import ProviderResponseError
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunStatus
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.stream import ChatStreamEventType
from EvernightAI.infra.adapters.providers.anthropic.instance import (
    AnthropicProviderInstance,
)
from EvernightAI.infra.adapters.providers.gemini.instance import GeminiProviderInstance
from EvernightAI.infra.adapters.providers.gemini.mapper import (
    GeminiStreamNormalizer,
    from_gemini_response,
    to_gemini_request,
)
from EvernightAI.infra.adapters.providers.anthropic.mapper import (
    from_anthropic_response,
    to_anthropic_request,
)
from EvernightAI.infra.adapters.providers.sse import iter_sse_json
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolApprovalStatus,
    ToolDefinition,
)


def message(text: str) -> Content:
    return Content(
        role=MessageRole.USER,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def sse(event: str | None, data: dict[str, Any]) -> str:
    return (f"event: {event}\n" if event else "") + f"data: {json.dumps(data)}\n\n"


def anthropic_stream(blocks: list[dict[str, Any]], reason: str) -> str:
    result = sse(
        "message_start", {"message": {"id": "response", "model": "test-model"}}
    )
    for index, block in enumerate(blocks):
        initial = dict(block)
        deltas = []
        for field, delta_type in (
            ("text", "text_delta"),
            ("thinking", "thinking_delta"),
            ("signature", "signature_delta"),
        ):
            if field in block:
                initial[field] = ""
                deltas.append({"type": delta_type, field: block[field]})
        if block["type"] == "tool_use":
            initial["input"] = {}
            deltas.append(
                {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
            )
        result += sse("content_block_start", {"index": index, "content_block": initial})
        for delta in deltas:
            result += sse("content_block_delta", {"index": index, "delta": delta})
        result += sse("content_block_stop", {"index": index})
    return (
        result
        + sse("message_delta", {"delta": {"stop_reason": reason}})
        + sse("message_stop", {})
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_type,native_ids",
    [
        (ProviderType.ANTHROPIC, False),
        (ProviderType.GOOGLE, False),
        (ProviderType.GOOGLE, True),
    ],
)
@pytest.mark.parametrize("streaming", [False, True])
async def test_agent_tool_roundtrip_preserves_signed_blocks_after_sqlite_reload(
    tmp_path: Path,
    provider_type: ProviderType,
    native_ids: bool,
    streaming: bool,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    executed: list[str] = []
    requests: list[dict[str, Any]] = []
    if provider_type is ProviderType.GOOGLE:
        blocks = [
            {"text": "thought summary", "thought": True},
            {
                "functionCall": {"name": "lookup", "args": {"q": "a"}},
                "thoughtSignature": "signature-a",
            },
            {"text": "Between calls"},
            {"functionCall": {"name": "lookup", "args": {"q": "b"}}},
            {"text": "", "thoughtSignature": "signature-last"},
        ]
        final_blocks = [{"text": "Finished", "thoughtSignature": "final-signature"}]
        if native_ids:
            blocks[1]["functionCall"]["id"] = "call-a"
            blocks[3]["functionCall"]["id"] = "call-b"
    else:
        blocks = [
            {
                "type": "thinking",
                "thinking": "thought summary",
                "signature": "signature-a",
            },
            {"type": "tool_use", "id": "call-a", "name": "lookup", "input": {"q": "a"}},
            {"type": "text", "text": "Between calls"},
            {"type": "tool_use", "id": "call-b", "name": "lookup", "input": {"q": "b"}},
        ]
        final_blocks = [{"type": "text", "text": "Finished"}]

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        first = len(requests) == 1
        output = blocks if first else final_blocks
        if provider_type is ProviderType.GOOGLE:
            if streaming:
                # Each function call starts at part index zero in a separate frame.
                body = "".join(
                    sse(
                        None,
                        {
                            "responseId": "response",
                            "modelVersion": "test-model",
                            "candidates": [{"content": {"parts": [part]}}],
                        },
                    )
                    for part in output
                )
                body += sse(
                    None,
                    {
                        "responseId": "response",
                        "candidates": [{"finishReason": "STOP"}],
                    },
                )
                return httpx.Response(200, text=body)
            return httpx.Response(
                200,
                json={
                    "responseId": "response",
                    "modelVersion": "test-model",
                    "candidates": [
                        {"content": {"parts": output}, "finishReason": "STOP"}
                    ],
                },
            )
        reason = "tool_use" if first else "end_turn"
        if streaming:
            return httpx.Response(200, text=anthropic_stream(output, reason))
        return httpx.Response(
            200,
            json={
                "id": "response",
                "model": "test-model",
                "content": output,
                "stop_reason": reason,
            },
        )

    tool = ToolDefinition(
        name="lookup",
        description="Lookup a value",
        requires_approval=True,
        parameters_schema={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
    )

    async def lookup(arguments: dict[str, Any]) -> dict[str, Any]:
        executed.append(arguments["q"])
        return {"value": arguments["q"]}

    async def runtime_with_client():
        runtime = create_sqlite_runtime(database, filesystem_root=tmp_path)
        runtime.tool_register.register(tool, lookup)
        await runtime.providers.create(
            ProviderConfig(provider_id="native", name="Native", type=provider_type)
        )
        if not requests:
            await runtime.contexts.create(Context(context_id="ctx"))
        provider = await runtime.providers.get("native")
        await cast(Any, provider)._client.aclose()
        cast(Any, provider)._client = httpx.AsyncClient(
            base_url="https://native.test", transport=httpx.MockTransport(handle)
        )
        return runtime

    runtime = await runtime_with_client()
    try:
        state = await AgentRunApplication(runtime).start(
            AgentRunRequest(
                provider_id="native",
                context_id="ctx",
                model_id="test-model",
                messages=[message("Lookup both values")],
                tools=[tool],
                metadata={"run_id": "roundtrip", "stream": streaming},
            )
        )
        assert state.status is AgentRunStatus.PAUSED
        assert not executed
        assert state.response is not None
        assert state.response.message.content == [
            ContentPart(type=ContentPartType.TEXT, text="Between calls")
        ]
        calls = state.response.message.tool_calls or []
        assert len(calls) == 2
        assert len({call.tool_call_id for call in calls}) == 2
        if native_ids:
            assert [call.tool_call_id for call in calls] == ["call-a", "call-b"]
    finally:
        await runtime.close()

    # The checkpoint and pending approvals must survive a process restart.
    runtime = await runtime_with_client()
    try:
        app = AgentRunApplication(runtime)
        restored = app.get_state("roundtrip")
        assert restored.response == state.response
        state = restored
        for _ in range(2):
            approvals = [
                ToolApprovalDecision(
                    approval_id=approval.approval_id,
                    tool_call_id=approval.tool_call_id,
                    status=ToolApprovalStatus.APPROVED,
                )
                for approval in state.pending_approval_requests
            ]
            state = await app.resume("roundtrip", approvals)
            if state.status is AgentRunStatus.FINISHED:
                break
        assert state.status is AgentRunStatus.FINISHED
        assert executed == ["a", "b"]
        assert len(requests) == 2
        assert state.response is not None
        assert state.response.message.content == [
            ContentPart(type=ContentPartType.TEXT, text="Finished")
        ]
        if provider_type is ProviderType.GOOGLE:
            assistant = next(c for c in requests[1]["contents"] if c["role"] == "model")
            assert assistant["parts"] == blocks
            results = [
                p["functionResponse"]
                for c in requests[1]["contents"]
                for p in c["parts"]
                if "functionResponse" in p
            ]
            assert [r["name"] for r in results] == ["lookup", "lookup"]
            if native_ids:
                assert [r["id"] for r in results] == ["call-a", "call-b"]
            tool_turns = [
                c
                for c in requests[1]["contents"]
                if any("functionResponse" in p for p in c["parts"])
            ]
            assert len(tool_turns) == 1
        else:
            assistant = next(
                m for m in requests[1]["messages"] if m["role"] == "assistant"
            )
            assert assistant["content"] == blocks
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", [ProviderType.ANTHROPIC, ProviderType.GOOGLE])
@pytest.mark.parametrize(
    "failure", ["error", "empty", "partial", "invalid-json", "invalid-shape"]
)
async def test_stream_errors_and_truncation_never_emit_done(
    provider_type: ProviderType,
    failure: str,
) -> None:
    bodies = {
        "empty": "",
        "invalid-json": "data: {invalid}\n\n",
        "invalid-shape": "data: []\n\n",
    }
    if provider_type is ProviderType.ANTHROPIC:
        bodies["error"] = sse(
            "error",
            {
                "type": "error",
                "error": {"type": "overloaded_error", "message": "Overloaded"},
            },
        )
        bodies["partial"] = sse(
            "message_start", {"message": {"id": "r", "model": "m"}}
        ) + sse("message_delta", {"delta": {"stop_reason": "end_turn"}})
        provider_class = AnthropicProviderInstance
    else:
        bodies["error"] = sse(
            None, {"error": {"status": "UNAVAILABLE", "message": "Overloaded"}}
        )
        bodies["partial"] = sse(
            None, {"candidates": [{"content": {"parts": [{"text": "partial"}]}}]}
        )
        provider_class = GeminiProviderInstance
    provider = provider_class(
        ProviderConfig(provider_id="test", name="Test", type=provider_type)
    )
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://test.invalid",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=bodies[failure])
        ),
    )
    events = []
    try:
        stream = await provider.chat_stream(
            ChatRequest(model_id="m", messages=[message("hello")])
        )
        if failure == "error":
            events = [event async for event in stream]
            assert events[-1].event_type is ChatStreamEventType.ERROR
            assert events[-1].error_message == "Overloaded"
        else:
            with pytest.raises(ProviderResponseError):
                async for event in stream:
                    events.append(event)
        assert all(event.event_type is not ChatStreamEventType.DONE for event in events)
    finally:
        await provider.close()


def test_gemini_preserves_signature_after_finish_frame_and_stable_call_ids() -> None:
    normalizer = GeminiStreamNormalizer()
    parts = [
        {
            "functionCall": {"name": "lookup", "args": {"q": "a"}},
            "thoughtSignature": "first",
        },
        {"functionCall": {"name": "lookup", "args": {"q": "b"}}},
        {"text": "", "thoughtSignature": "tail"},
    ]
    emitted = []
    for part in parts[:2]:
        emitted.extend(
            normalizer.map_chunk({"candidates": [{"content": {"parts": [part]}}]})
        )
    # Some frames omit responseId, and signatures may arrive in an empty-text frame.
    normalizer.map_chunk(
        {"responseId": "late-response-id", "candidates": [{"finishReason": "STOP"}]}
    )
    normalizer.map_chunk({"candidates": [{"content": {"parts": [parts[2]]}}]})
    completed = normalizer.completed_event()
    assert completed.message is not None
    calls = completed.message.tool_calls or []
    assert len({call.tool_call_id for call in calls}) == 2
    assert [call.tool_call_id for call in calls] == [
        event.tool_call_id for event in emitted
    ]
    assert to_gemini_request([completed.message])["contents"][0]["parts"] == parts
    other = GeminiStreamNormalizer()
    event = other.map_chunk({"candidates": [{"content": {"parts": [parts[0]]}}]})[0]
    assert event.tool_call_id not in {call.tool_call_id for call in calls}


def test_gemini_rejects_duplicate_native_call_ids() -> None:
    part = {"functionCall": {"id": "duplicate", "name": "lookup", "args": {}}}
    with pytest.raises(ProviderResponseError, match="duplicate"):
        from_gemini_response(
            {"candidates": [{"content": {"parts": [part, part]}}]}, "m"
        )
    normalizer = GeminiStreamNormalizer()
    chunk = {"candidates": [{"content": {"parts": [part]}}]}
    normalizer.map_chunk(chunk)
    with pytest.raises(ProviderResponseError, match="duplicate"):
        normalizer.map_chunk(chunk)


def test_gemini_zero_argument_tools_match_stream_and_nonstream() -> None:
    chunk = {
        "responseId": "response",
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {"name": "list_tools"},
                            "thoughtSignature": "signature",
                        }
                    ]
                },
                "finishReason": "STOP",
            }
        ],
    }
    normalizer = GeminiStreamNormalizer()
    events = normalizer.map_chunk(chunk)
    final = normalizer.completed_event()
    assert final.message is not None
    response = from_gemini_response(chunk, "m")
    assert final.message == response.message
    assert events[0].tool_call is not None
    assert events[0].tool_call.tool_call == {"name": "list_tools", "arguments": {}}
    assert (
        to_gemini_request([final.message])["contents"][0]["parts"]
        == chunk["candidates"][0]["content"]["parts"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", [ProviderType.ANTHROPIC, ProviderType.GOOGLE])
@pytest.mark.parametrize("failure", ["error", "partial"])
async def test_agent_saves_stream_failures_without_completed_response(
    tmp_path: Path, provider_type: ProviderType, failure: str
) -> None:
    if provider_type is ProviderType.ANTHROPIC:
        body = anthropic_stream([{"type": "text", "text": "partial"}], "end_turn")
        body = body[: body.index("event: message_delta")]
        if failure == "error":
            body += sse(
                "error",
                {
                    "type": "error",
                    "error": {"type": "overloaded_error", "message": "Overloaded"},
                },
            )
    else:
        body = sse(
            None, {"candidates": [{"content": {"parts": [{"text": "partial"}]}}]}
        )
        if failure == "error":
            body += sse(
                None, {"error": {"status": "UNAVAILABLE", "message": "Overloaded"}}
            )
    runtime = create_sqlite_runtime(
        tmp_path / "runtime.sqlite3", filesystem_root=tmp_path
    )
    try:
        await runtime.providers.create(
            ProviderConfig(provider_id="native", name="Native", type=provider_type)
        )
        await runtime.contexts.create(Context(context_id="ctx"))
        provider = await runtime.providers.get("native")
        await cast(Any, provider)._client.aclose()
        cast(Any, provider)._client = httpx.AsyncClient(
            base_url="https://native.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=body)
            ),
        )
        app = AgentRunApplication(runtime)
        with pytest.raises(ProviderResponseError):
            await app.start(
                AgentRunRequest(
                    provider_id="native",
                    context_id="ctx",
                    model_id="m",
                    messages=[message("Hello")],
                    metadata={"run_id": "failure", "stream": True},
                )
            )
        saved = app.get_state("failure")
        assert saved.status is AgentRunStatus.FAILED
        assert saved.response is None
    finally:
        await runtime.close()


@pytest.mark.parametrize("provider_type", [ProviderType.ANTHROPIC, ProviderType.GOOGLE])
@pytest.mark.parametrize("mutation", ["text", "arguments", "id"])
def test_preserved_content_cannot_silently_override_edited_messages(
    provider_type: ProviderType, mutation: str
) -> None:
    if provider_type is ProviderType.GOOGLE:
        mapped = from_gemini_response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "original"},
                                {
                                    "functionCall": {
                                        "id": "call",
                                        "name": "lookup",
                                        "args": {"q": "a"},
                                    },
                                    "thoughtSignature": "signature",
                                },
                            ]
                        }
                    }
                ]
            },
            "m",
        )
    else:
        mapped = from_anthropic_response(
            {
                "model": "m",
                "content": [
                    {"type": "text", "text": "original"},
                    {
                        "type": "tool_use",
                        "id": "call",
                        "name": "lookup",
                        "input": {"q": "a"},
                    },
                ],
            }
        )
    assistant = Content.model_validate_json(mapped.message.model_dump_json())
    if mutation == "text":
        assert assistant.content
        assistant.content[0].text = "edited"
    elif mutation == "arguments":
        assert assistant.tool_calls
        assistant.tool_calls[0].tool_call["arguments"] = {"q": "edited"}
    else:
        assert assistant.tool_calls
        assistant.tool_calls[0].tool_call_id = "edited-id"
    with pytest.raises(ChatInputError, match="does not match"):
        if provider_type is ProviderType.GOOGLE:
            to_gemini_request([assistant])
        else:
            to_anthropic_request([assistant], "m")


@pytest.mark.asyncio
async def test_sse_parser_preserves_named_multiline_frames() -> None:
    response = httpx.Response(
        200,
        text=': heartbeat\nevent: error\nid: 4\ndata: {"error":\ndata: {"message":"Overloaded"}}\n\n',
    )
    frames = [frame async for frame in iter_sse_json(response)]
    assert frames == [("error", {"error": {"message": "Overloaded"}})]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", [ProviderType.ANTHROPIC, ProviderType.GOOGLE])
@pytest.mark.parametrize(
    "scope,limit", [("provider", 4096), ("model", 8192), ("request", 16384)]
)
async def test_output_limit_precedence_matches_chat_and_stream(
    provider_type: ProviderType, scope: str, limit: int
) -> None:
    config = ProviderConfig(
        provider_id="test",
        name="Test",
        type=provider_type,
        metadata={"max_output_tokens": 4096},
        model={
            "m": ProviderModelConfig(
                model_id="m",
                metadata={"max_output_tokens": 8192} if scope != "provider" else {},
            )
        },
    )
    provider = (
        AnthropicProviderInstance(config)
        if provider_type is ProviderType.ANTHROPIC
        else GeminiProviderInstance(config)
    )
    await provider._client.aclose()
    payloads = []

    def handle(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        if provider_type is ProviderType.GOOGLE:
            response = {
                "modelVersion": "m",
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "OK"}]}}
                ],
            }
            return (
                httpx.Response(200, json=response)
                if "streamGenerateContent" not in request.url.path
                else httpx.Response(200, text=sse(None, response))
            )
        response = {"model": "m", "content": [{"type": "text", "text": "OK"}]}
        return (
            httpx.Response(200, json=response)
            if not payloads[-1].get("stream")
            else httpx.Response(
                200, text=anthropic_stream(response["content"], "end_turn")
            )
        )

    provider._client = httpx.AsyncClient(
        base_url="https://test.invalid", transport=httpx.MockTransport(handle)
    )
    try:
        request = ChatRequest(
            model_id="m",
            messages=[message("Hello")],
            metadata={"max_output_tokens": limit} if scope == "request" else {},
        )
        await provider.chat(request)
        stream = await provider.chat_stream(request)
        _ = [event async for event in stream]
        assert len(payloads) == 2
        assert all(
            (
                p["max_tokens"]
                if provider_type is ProviderType.ANTHROPIC
                else p["generationConfig"]["maxOutputTokens"]
            )
            == limit
            for p in payloads
        )
        for value in (True, 0, -1, 1.5, "8192", None):
            request.metadata["max_output_tokens"] = value
            with pytest.raises(ChatInputError, match="positive integer"):
                await provider.chat(request)
            with pytest.raises(ChatInputError, match="positive integer"):
                await provider.chat_stream(request)
        assert len(payloads) == 2
    finally:
        await provider.close()
