from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.interface import ChatInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import SSEProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    ChatSkill,
    Content,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery, MemorySelection
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.core.schema.skill import SkillCapability
from EvernightAI.core.schema.tool import ToolDefinition
from EvernightAI.application.skill_prompt import compose_skill_prompted_chat_request


class ChatApplication(ChatInterfaceProtocol):
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
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest:
        context = await self._runtime.contexts.get(context_id)
        selected_memories = (
            await self.select_memories(memory_query)
            if memory_query is not None
            else None
        )

        request = self._runtime.context_strategy.compose_chat_request(
            context,
            model_id=model_id,
            messages=messages,
            memory_selection=selected_memories,
            tools=tools,
            metadata=metadata,
        )
        return request.model_copy(update={"skills": skills})

    async def chat(self, provider_id: str, request: ChatRequest) -> ChatResponse:
        request = await compose_skill_prompted_chat_request(
            self._runtime,
            request,
            SkillCapability.CHAT,
        )
        return await self._runtime.providers.chat(provider_id, request)

    async def chat_with_context(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatResponse:
        request = await self.organize_chat_request(
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
        )
        response = await self.chat(provider_id, request)

        for message in messages:
            await self._runtime.contexts.append(context_id, message)
        await self._runtime.contexts.append(context_id, response.message)

        return response

    async def chat_stream(self, provider_id: str, request: ChatRequest) -> SSEProtocol:
        request = await compose_skill_prompted_chat_request(
            self._runtime,
            request,
            SkillCapability.CHAT,
        )
        return await self._runtime.providers.chat_stream(provider_id, request)

    async def close(self) -> None:
        await self._runtime.close()
