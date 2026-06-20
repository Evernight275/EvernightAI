from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import SSEProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery, MemorySelection
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.core.schema.tool import ToolDefinition


class ChatApplication:
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def create_provider(
        self,
        config: ProviderConfig,
    ) -> ProviderInstanceProtocol:
        return await self._runtime.providers.create(config)

    async def create_context(self, context: Context) -> Context:
        return await self._runtime.contexts.create(context)

    async def get_context(self, context_id: str) -> Context:
        return await self._runtime.contexts.get(context_id)

    async def append_context(self, context_id: str, message: Content) -> Context:
        return await self._runtime.contexts.append(context_id, message)

    async def replace_context(self, context: Context) -> Context:
        return await self._runtime.contexts.replace(context)

    async def list_contexts(self) -> list[Context]:
        return await self._runtime.contexts.list_contexts()

    async def delete_context(self, context_id: str) -> None:
        await self._runtime.contexts.delete(context_id)

    async def create_memory(self, memory: MemoryItem) -> MemoryItem:
        return await self._runtime.memories.create(memory)

    async def get_memory(self, memory_id: str) -> MemoryItem:
        return await self._runtime.memories.get(memory_id)

    async def list_memories(self) -> list[MemoryItem]:
        return await self._runtime.memories.list_memories()

    async def delete_memory(self, memory_id: str) -> None:
        await self._runtime.memories.delete(memory_id)

    async def select_memories(
        self,
        query: MemoryQuery | None = None,
    ) -> MemorySelection:
        memories = await self._runtime.memories.list_memories()
        return self._runtime.memory_strategy.select(memories, query)

    async def organize_chat_request(
        self,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        memory_query: MemoryQuery | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest:
        context = await self._runtime.contexts.get(context_id)
        selected_memories: MemorySelection | None = None
        organized_messages = list(messages or [])
        request_metadata: dict[str, object] = dict(metadata or {})

        if memory_query is not None:
            selected_memories = await self.select_memories(memory_query)
            memory_message = self._compose_memory_message(selected_memories)
            if memory_message is not None:
                organized_messages = [memory_message, *organized_messages]
            request_metadata["memory_ids"] = [
                memory.memory_id for memory in selected_memories.memories
            ]
            request_metadata["memory_selection"] = dict(selected_memories.metadata)

        return self._runtime.context_organizer.to_chat_request(
            context,
            model_id=model_id,
            messages=organized_messages,
            tools=tools,
            metadata=request_metadata,
        )

    async def chat(self, provider_id: str, request: ChatRequest) -> ChatResponse:
        return await self._runtime.providers.chat(provider_id, request)

    async def chat_with_context(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatResponse:
        request = await self.organize_chat_request(
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            tools=tools,
            metadata=metadata,
        )
        response = await self.chat(provider_id, request)

        for message in messages:
            await self._runtime.contexts.append(context_id, message)
        await self._runtime.contexts.append(context_id, response.message)

        return response

    async def chat_stream(self, provider_id: str, request: ChatRequest) -> SSEProtocol:
        return await self._runtime.providers.chat_stream(provider_id, request)

    async def close(self) -> None:
        await self._runtime.close()

    def _compose_memory_message(self, selection: MemorySelection) -> Content | None:
        if not selection.memories:
            return None

        lines = ["Relevant memory:"]
        for memory in selection.memories:
            lines.append(f"- {memory.kind.value}: {memory.content}")

        return Content(
            role=MessageRole.SYSTEM,
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text="\n".join(lines),
                )
            ],
            metadata={
                "source": "memory",
                "memory_ids": [memory.memory_id for memory in selection.memories],
            },
        )
