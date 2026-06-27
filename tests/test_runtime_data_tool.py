import pytest

from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.domain.tool import ToolManager
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.content import MessageRole
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.registrations.tool.runtime_data import (
    register_runtime_data_tools,
)


@pytest.mark.asyncio
async def test_runtime_data_tools_append_context_message_and_write_memory() -> None:
    runtime = create_runtime()
    register_runtime_data_tools(
        runtime.tool_register,
        contexts=runtime.contexts,
        memories=runtime.memories,
    )
    manager = ToolManager(runtime.tool_register, runtime.tool_safety_policy)
    await runtime.contexts.create(Context(context_id="ctx-1"))

    context_result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "append_context_message",
                "arguments": {
                    "context_id": "ctx-1",
                    "role": "user",
                    "text": "remember this",
                },
            },
            metadata={"approved": True},
        )
    )
    memory_result = await manager.execute(
        ToolCall(
            tool_call_id="call-2",
            tool_call={
                "name": "write_memory",
                "arguments": {
                    "memory_id": "mem-1",
                    "content": "User prefers concise answers",
                    "kind": "preference",
                },
            },
            metadata={"approved": True},
        )
    )

    context = await runtime.contexts.get("ctx-1")
    memory = await runtime.memories.get("mem-1")

    assert context.messages[0].role is MessageRole.USER
    assert context.messages[0].content is not None
    assert context.messages[0].content[0].text == "remember this"
    assert context_result.tool_call_result["context_id"] == "ctx-1"
    assert memory.content == "User prefers concise answers"
    assert memory_result.tool_call_result["memory_id"] == "mem-1"
