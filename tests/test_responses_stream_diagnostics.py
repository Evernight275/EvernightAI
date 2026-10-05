import json

import httpx
import pytest
from openai import AsyncOpenAI

from EvernightAI.core.error.provider import ProviderResponseError
from EvernightAI.core.schema.content import ChatRequest
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.infra.adapters.providers.openai_responses.instance import (
    OpenAIResponsesProviderInstance,
)
from EvernightAI.infra.adapters.providers.openai_responses.stream_diagnostics import (
    ResponsesStreamDiagnostics,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,reason",
    [
        ("no_events", "before a final response event"),
        ("whitespace", "last event: response.output_text.delta"),
        ("completed", "empty or whitespace-only output"),
        ("incomplete", "incomplete (max_output_tokens)"),
        ("reasoning_only", "reasoning only"),
    ],
)
async def test_empty_responses_stream_explains_its_failure_without_retrying(
    case, reason
):
    payloads = []
    if case == "whitespace":
        payloads.append(
            {
                "type": "response.output_text.delta",
                "delta": " ",
                "item_id": "msg-1",
                "content_index": 0,
                "output_index": 0,
                "sequence_number": 1,
            }
        )
    elif case != "no_events":
        status = "incomplete" if case == "incomplete" else "completed"
        payloads.append(
            {
                "type": f"response.{status}",
                "sequence_number": 1,
                "response": {
                    "id": "resp-empty",
                    "object": "response",
                    "created_at": 123,
                    "model": "test-model",
                    "status": status,
                    "parallel_tool_calls": True,
                    "tool_choice": "auto",
                    "tools": [],
                    "output": [
                        {
                            "id": "reasoning-1",
                            "type": "reasoning",
                            "summary": [
                                {
                                    "type": "summary_text",
                                    "text": "private output canary",
                                }
                            ],
                        }
                    ]
                    if case == "reasoning_only"
                    else [],
                    "incomplete_details": {"reason": "max_output_tokens"}
                    if case == "incomplete"
                    else None,
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 50,
                        "total_tokens": 60,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens_details": {"reasoning_tokens": 50},
                    },
                },
            }
        )
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(
            200,
            text="".join(f"data: {json.dumps(event)}\n\n" for event in payloads)
            + "data: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    provider = OpenAIResponsesProviderInstance(
        ProviderConfig(
            provider_id="test", name="Test", type=ProviderType.OPENAI_RESPONSES
        )
    )
    await provider._client.close()
    provider._client = AsyncOpenAI(
        api_key="test",
        base_url="https://upstream.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    try:
        stream = await provider.chat_stream(
            ChatRequest(model_id="test-model", messages=[])
        )
        with pytest.raises(ProviderResponseError) as caught:
            _ = [event async for event in stream]
        assert reason in str(caught.value)
        assert caught.value.detail is not None
        detail = json.loads(caught.value.detail)
        assert "private output canary" not in caught.value.detail
        assert len(calls) == 1
        if case == "no_events":
            assert detail["event_counts"] == {}
        if case == "reasoning_only":
            assert detail["output_types"] == ["reasoning"]
            assert detail["output_tokens"] == 50
            assert detail["reasoning_tokens"] == 50
        if case == "incomplete":
            assert detail["incomplete_reason"] == "max_output_tokens"
    finally:
        await provider.close()


def test_diagnostics_counts_are_bounded_and_do_not_retain_response_content():
    diagnostic = ResponsesStreamDiagnostics()
    for index in range(1000):
        diagnostic.observe(
            {"type": f"unknown-{index}", "delta": "private output canary"}
        )
    error = diagnostic.empty_output_error()
    assert len(diagnostic.event_counts) <= 65
    assert sum(diagnostic.event_counts.values()) == 1000
    assert error.detail is not None
    assert "private output canary" not in error.detail
    diagnostic.observe(
        {
            "type": "response.completed",
            "response": {"status": "completed", "output": []},
        }
    )
    assert diagnostic.final_event == "response.completed"
    assert diagnostic.last_event == "response.completed"
    assert "empty or whitespace-only" in str(diagnostic.empty_output_error())


@pytest.mark.parametrize(
    "limit,expected",
    [(None, None), (4096, 4096), (0, 0), (-1, None), (True, None), ("4096", None)],
)
def test_diagnostics_preserve_only_numeric_upstream_output_limits(limit, expected):
    diagnostic = ResponsesStreamDiagnostics()
    diagnostic.observe(
        {
            "type": "response.incomplete",
            "response": {
                "status": "incomplete",
                "max_output_tokens": limit,
                "incomplete_details": {"reason": "max_output_tokens"},
            },
        }
    )
    error = diagnostic.empty_output_error()
    assert error.detail is not None
    detail = json.loads(error.detail)
    assert detail["max_output_tokens"] == expected
    assert detail["output_tokens"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("declared", [False, True])
async def test_responses_reasoning_control_uses_the_sdk_wire_format(
    streaming, declared
):
    calls = []

    def upstream(request):
        calls.append(json.loads(request.content))
        response = {
            "id": "resp-1",
            "object": "response",
            "created_at": 123,
            "model": "test-model",
            "status": "completed",
            "output": [
                {
                    "id": "msg-1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "OK", "annotations": []}
                    ],
                }
            ],
        }
        if streaming:
            event = {
                "type": "response.completed",
                "sequence_number": 1,
                "response": response,
            }
            return httpx.Response(
                200,
                text=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=response)

    provider = OpenAIResponsesProviderInstance(
        ProviderConfig(
            provider_id="test",
            name="Test",
            type=ProviderType.OPENAI_RESPONSES,
            model={"test-model": ProviderModelConfig(model_id="test-model")}
            if declared
            else {},
        )
    )
    await provider._client.close()
    provider._client = AsyncOpenAI(
        api_key="test",
        base_url="https://upstream.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    try:
        request = ChatRequest(
            model_id="test-model",
            messages=[],
            metadata={
                "reasoning_effort": "low",
                "timeout_seconds": 12,
                "request_id": "private metadata",
            },
        )
        if streaming:
            stream = await provider.chat_stream(request)
            events = [event async for event in stream]
            assert "".join(event.text_delta or "" for event in events) == "OK"
        else:
            result = await provider.chat(request)
            assert result.message.content is not None
            assert result.message.content[0].text == "OK"
        assert len(calls) == 1
        assert calls[0]["reasoning"] == {"effort": "low"}
        assert "reasoning_effort" not in calls[0]
        assert "max_output_tokens" not in calls[0]
        assert "timeout_seconds" not in calls[0]
        assert "request_id" not in calls[0]
    finally:
        await provider.close()
