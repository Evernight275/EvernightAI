import json

import httpx
import pytest
from openai import AsyncOpenAI

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime_with_agent_storage
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.provider import ProviderConfig, ProviderType
from EvernightAI.core.schema.tool import ToolDefinition, ToolReplayPolicy
from EvernightAI.infra.adapters.providers.openai_responses.instance import (
    OpenAIResponsesProviderInstance,
)
from EvernightAI.interface.http.app import create_http_app
from tests.fakes.agent import (
    InMemoryAgentRunStateRegister,
    InMemoryAgentTraceRegister,
)


def final_response(text="Hello", *, status="completed", refusal=False):
    return {
        "type": f"response.{status}",
        "sequence_number": 3,
        "response": {
            "id": "resp-1",
            "created_at": 123,
            "model": "undeclared-model",
            "object": "response",
            "status": status,
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "output": [
                {
                    "id": "msg-1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "refusal", "refusal": text}
                        if refusal
                        else {"type": "output_text", "text": text, "annotations": []}
                    ],
                }
            ]
            if text
            else [],
        },
    }


def text_event(event_type, text):
    return {
        "type": event_type,
        "sequence_number": 0,
        "item_id": "msg-1",
        "output_index": 0,
        "content_index": 0,
        "logprobs": [],
        "delta" if event_type.endswith("delta") else "text": text,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "completed_only",
        "text_done",
        "part_done",
        "part_done_only",
        "part_done_partial",
        "part_done_duplicate",
        "part_done_refusal",
        "item_done",
        "partial_delta",
        "full_delta",
        "refusal",
        "incomplete",
        "failed",
        "error",
        "mismatch",
        "empty",
        "whitespace",
    ],
)
async def test_responses_wire_events_reach_chat_sse_and_persist(case):
    final = final_response()
    payloads = [final]
    expected = "Hello"
    error = None
    if case == "text_done":
        payloads.insert(0, text_event("response.output_text.done", "Hello"))
    elif case.startswith("part_done"):
        part = final["response"]["output"][0]["content"][0]
        if case == "part_done_refusal":
            expected = "Cannot comply."
            final = final_response(expected, refusal=True)
            part = final["response"]["output"][0]["content"][0]
        part_done = {
            "type": "response.content_part.done",
            "sequence_number": 1,
            "item_id": "msg-1",
            "output_index": 0,
            "content_index": 0,
            "part": part,
        }
        payloads = [part_done, final]
        if case == "part_done_only":
            payloads = [part_done]
        elif case == "part_done_partial":
            payloads.insert(0, text_event("response.output_text.delta", "He"))
        elif case == "part_done_duplicate":
            payloads = [
                text_event("response.output_text.done", "Hello"),
                part_done,
                part_done,
                final,
            ]
    elif case == "item_done":
        payloads.insert(
            0,
            {
                "type": "response.output_item.done",
                "sequence_number": 1,
                "output_index": 0,
                "item": final["response"]["output"][0],
            },
        )
    elif case == "partial_delta":
        payloads = [
            text_event("response.output_text.delta", "He"),
            text_event("response.output_text.done", "Hello"),
            final,
        ]
    elif case == "full_delta":
        payloads = [
            text_event("response.output_text.delta", "Hello"),
            text_event("response.output_text.done", "Hello"),
            final,
        ]
    elif case == "refusal":
        expected = "Cannot comply."
        payloads = [final_response(expected, refusal=True)]
    elif case == "incomplete":
        payloads = [final_response(status="incomplete")]
    elif case == "failed":
        final = final_response("", status="failed")
        final["response"]["error"] = {
            "code": "model_unavailable",
            "message": "Upstream model unavailable",
        }
        payloads = [text_event("response.output_text.delta", " "), final]
        error = "Upstream model unavailable"
    elif case == "empty":
        payloads = [final_response("")]
        error = "ended without text or tool calls"
    elif case == "error":
        payloads = [
            {
                "type": "error",
                "code": "server_error",
                "message": "Relay failed",
                "sequence_number": 0,
            }
        ]
        error = "Relay failed"
    elif case == "mismatch":
        payloads = [text_event("response.output_text.delta", "Other"), final]
        error = "final text does not match streamed text"
    elif case == "whitespace":
        payloads = [text_event("response.output_text.delta", " ")]
        error = "ended without text or tool calls"

    def upstream(request):
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["model"] == "undeclared-model"
        wire = "".join(
            f"event: {p['type']}\ndata: {json.dumps(p)}\n\n" for p in payloads
        )
        return httpx.Response(
            200,
            text=wire + "data: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    config = ProviderConfig(
        provider_id="responses", name="Responses", type=ProviderType.OPENAI_RESPONSES
    )
    provider = OpenAIResponsesProviderInstance(config)
    await provider._client.close()
    provider._client = AsyncOpenAI(
        api_key="test",
        base_url="https://upstream.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    runtime = create_runtime_with_agent_storage(
        agent_state_register=InMemoryAgentRunStateRegister(),
        agent_trace_register=InMemoryAgentTraceRegister(),
    )

    async def build_provider(_):
        return provider

    runtime.provider_factory.register(ProviderType.OPENAI_RESPONSES, build_provider)
    await runtime.providers.create(config)
    await runtime.contexts.create(Context(context_id="ctx-responses"))
    app = create_http_app(create_interface(runtime))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local.test"
        ) as client:
            response = await client.post(
                "/agent-runs/stream",
                json={
                    "provider_id": "responses",
                    "context_id": "ctx-responses",
                    "model_id": "undeclared-model",
                    "messages": [
                        {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
                    ],
                    "metadata": {"stream": True, "run_id": "responses-wire"},
                },
            )
            assert response.status_code == 200, response.text
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            state = (await client.get("/agent-runs/responses-wire")).json()
            if error:
                assert state["status"] == "failed"
                assert any(
                    error in (event.get("error_message") or "")
                    or error in (event.get("error") or {}).get("message", "")
                    for event in events
                ), events
                assert not any(
                    event.get("event_type") == "chat_completed" for event in events
                )
                if case in {"empty", "whitespace"}:
                    stopped = next(
                        event
                        for event in state["trace"]
                        if event["event_type"] == "run_stopped"
                    )
                    detail = json.loads(stopped["payload"]["error_detail"])
                    assert detail["last_event"] == (
                        "response.completed"
                        if case == "empty"
                        else "response.output_text.delta"
                    )
            else:
                assert state["status"] == "finished"
                assert (
                    "".join(event.get("text_delta") or "" for event in events)
                    == expected
                )
                assert state["response"]["message"]["content"][0]["text"] == expected
                context = (
                    await client.get(f"/contexts/{state['request']['context_id']}")
                ).json()
                assert context["messages"][-1]["content"][0]["text"] == expected
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_deltas", [False, True])
@pytest.mark.parametrize("reply_only", [False, True])
async def test_responses_wire_tool_call_executes_once_and_survives_state_reload(
    with_deltas: bool,
    reply_only: bool,
):
    requests = []
    executions = []
    item = {
        "id": "fc-1",
        "type": "function_call",
        "call_id": "call-add",
        "name": "add",
        "arguments": '{"left":1,"right":2}',
        "status": "completed",
    }

    def upstream(request):
        body = json.loads(request.content)
        requests.append(body)
        for tool in body.get("tools", []):
            assert tool["strict"] is False
        final = final_response("The result is 3")
        payloads = []
        if len(requests) == 1:
            final["response"]["output"] = [item]
            if with_deltas:
                payloads = [
                    {
                        "type": "response.output_item.added",
                        "sequence_number": 0,
                        "output_index": 0,
                        "item": {**item, "arguments": "", "status": "in_progress"},
                    },
                    {
                        "type": "response.function_call_arguments.delta",
                        "sequence_number": 1,
                        "item_id": "fc-1",
                        "output_index": 0,
                        "delta": item["arguments"],
                    },
                    {
                        "type": "response.function_call_arguments.done",
                        "sequence_number": 2,
                        "item_id": "fc-1",
                        "output_index": 0,
                        "arguments": item["arguments"],
                    },
                ]
        else:
            results = [
                part
                for part in body["input"]
                if part.get("type") == "function_call_output"
            ]
            assert len(results) == 1
            assert results[0]["call_id"] == "call-add"
            assert json.loads(results[0]["output"])["tool_call_result"] == {"result": 3}
        payloads.append(final)
        return httpx.Response(
            200,
            text="".join(f"data: {json.dumps(event)}\n\n" for event in payloads),
            headers={"content-type": "text/event-stream"},
        )

    config = ProviderConfig(
        provider_id="responses", name="Responses", type=ProviderType.OPENAI_RESPONSES
    )
    provider = OpenAIResponsesProviderInstance(config)
    await provider._client.close()
    provider._client = AsyncOpenAI(
        api_key="test",
        base_url="https://upstream.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    runtime = create_runtime_with_agent_storage(
        agent_state_register=InMemoryAgentRunStateRegister(),
        agent_trace_register=InMemoryAgentTraceRegister(),
    )

    async def build_provider(_):
        return provider

    async def add(arguments):
        executions.append(arguments)
        return {"result": arguments["left"] + arguments["right"]}

    runtime.provider_factory.register(ProviderType.OPENAI_RESPONSES, build_provider)
    runtime.tool_register.register(
        ToolDefinition(
            name="add",
            description="Add numbers",
            replay_policy=ToolReplayPolicy.SAFE,
            parameters_schema={
                "type": "object",
                "properties": {
                    "left": {"type": "integer"},
                    "right": {"type": "integer"},
                },
                "required": ["left", "right"],
            },
        ),
        add,
    )
    await runtime.providers.create(config)
    await runtime.contexts.create(Context(context_id="ctx-tool"))
    app = create_http_app(create_interface(runtime))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local.test"
        ) as client:
            response = await client.post(
                "/agent-runs/stream",
                json={
                    "provider_id": "responses",
                    "context_id": "ctx-tool",
                    "model_id": "undeclared-model",
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": "Add 1 and 2"}],
                        }
                    ],
                    "tools": [
                        tool.model_dump(mode="json")
                        for tool in runtime.tools.list_tools()
                    ]
                    if not reply_only
                    else [],
                    "max_tool_rounds": 0 if reply_only else 1,
                    "metadata": {"stream": True, "run_id": "responses-tool"},
                },
            )
            assert response.status_code == 200, response.text
            state = (await client.get("/agent-runs/responses-tool")).json()
            if reply_only:
                assert state["status"] == "failed"
                assert state["stop_reason"] == "tool_rounds_exhausted"
                assert executions == []
                assert len(requests) == 1
                assert not requests[0].get("tools")
                return
            assert state["status"] == "finished", response.text
            assert (
                state["response"]["message"]["content"][0]["text"] == "The result is 3"
            )
            tools = [
                event
                for event in state["trace"]
                if event["event_type"] == "tool_completed"
            ]
            assert len(tools) == 1
            assert tools[0]["metadata"]["duration_ms"] >= 0
            assert len(executions) == 1
            assert len(requests) == 2
            # Refresh reads persisted state and never executes the tool again.
            assert (await client.get("/agent-runs/responses-tool")).json() == state
            assert len(executions) == 1
    finally:
        await runtime.close()
