from collections.abc import AsyncIterator

from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.interface import ChatInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    ChatSkill,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import (
    MemoryItem,
    MemoryQuery,
    MemorySelection,
)
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.core.schema.skill import SkillCapability
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition
from EvernightAI.application.skill_prompt import compose_skill_prompted_chat_request
from EvernightAI.application.retry import mark_retry_messages
from EvernightAI.application.memory import select_memories_for_request


class ChatApplication(ChatInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def create_provider(
        self,
        config: ProviderConfig,
    ) -> ProviderInstanceProtocol:
        return await self._runtime.providers.create(config)

    async def create_context(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        return await self._runtime.contexts.create(
            context,
            principal_scope=principal_scope,
        )

    async def get_context(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        return await self._runtime.contexts.get(
            context_id,
            principal_scope=principal_scope,
        )

    async def append_context(
        self,
        context_id: str,
        message: Content,
        *,
        expected_revision: int | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        return await self._runtime.contexts.append(
            context_id,
            message,
            expected_revision=expected_revision,
            principal_scope=principal_scope,
        )

    async def replace_context(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        return await self._runtime.contexts.replace(
            context,
            principal_scope=principal_scope,
        )

    async def list_contexts(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[Context]:
        return await self._runtime.contexts.list_contexts(
            cursor=cursor,
            limit=limit,
            owner_id=owner_id,
            principal_scope=principal_scope,
        )

    async def delete_context(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        await self._runtime.contexts.delete(
            context_id,
            principal_scope=principal_scope,
        )

    async def create_memory(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        return await self._runtime.memories.create(
            memory,
            principal_scope=principal_scope,
        )

    async def get_memory(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        return await self._runtime.memories.get(
            memory_id,
            principal_scope=principal_scope,
        )

    async def replace_memory(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem:
        return await self._runtime.memories.replace(
            memory,
            principal_scope=principal_scope,
        )

    async def list_memories(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        query: MemoryQuery | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[MemoryItem]:
        return await self._runtime.memories.list_memories(
            cursor=cursor,
            limit=limit,
            owner_id=owner_id,
            query=query,
            principal_scope=principal_scope,
        )

    async def delete_memory(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        await self._runtime.memories.delete(
            memory_id,
            principal_scope=principal_scope,
        )

    async def select_memories(
        self,
        query: MemoryQuery | None = None,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemorySelection:
        memories = await self._runtime.memories.list_memories(
            principal_scope=principal_scope,
        )
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
        principal_scope: PrincipalScope | None = None,
    ) -> ChatRequest:
        context = await self._runtime.contexts.get(
            context_id,
            principal_scope=principal_scope,
        )
        selected_memories = await select_memories_for_request(
            self._runtime,
            explicit_query=memory_query,
            context_id=context.context_id,
            metadata=metadata,
            owner_id=context.owner_id,
            principal_scope=principal_scope,
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
        retry_from_message_index: int | None = None,
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> ChatResponse:
        await mark_retry_messages(
            self._runtime,
            context_id,
            retry_from_message_index,
            principal_scope=principal_scope,
        )
        request = await self.organize_chat_request(
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
            principal_scope=principal_scope,
        )
        response = await self.chat(provider_id, request)

        for message in messages:
            await self._runtime.contexts.append(
                context_id,
                message,
                principal_scope=principal_scope,
            )
        await self._runtime.contexts.append(
            context_id,
            response.message,
            principal_scope=principal_scope,
        )

        return response

    async def chat_stream(
        self, provider_id: str, request: ChatRequest
    ) -> ChatStreamProtocol:
        request = await compose_skill_prompted_chat_request(
            self._runtime,
            request,
            SkillCapability.CHAT,
        )
        return await self._runtime.providers.chat_stream(provider_id, request)

    async def chat_stream_with_context(
        self,
        provider_id: str,
        context_id: str,
        *,
        model_id: str,
        messages: list[Content],
        retry_from_message_index: int | None = None,
        memory_query: MemoryQuery | None = None,
        skills: list[ChatSkill] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> ChatStreamProtocol:
        await mark_retry_messages(
            self._runtime,
            context_id,
            retry_from_message_index,
            principal_scope=principal_scope,
        )
        request = await self.organize_chat_request(
            context_id,
            model_id=model_id,
            messages=messages,
            memory_query=memory_query,
            skills=skills,
            tools=tools,
            metadata=metadata,
            principal_scope=principal_scope,
        )
        stream = await self.chat_stream(provider_id, request)
        return _ContextAppendingChatStream(
            stream,
            self._runtime,
            context_id,
            messages,
            principal_scope,
        )

    async def close(self) -> None:
        await self._runtime.close()

class _ContextAppendingChatStream:
    def __init__(
        self,
        stream: ChatStreamProtocol,
        runtime: RuntimeProtocol,
        context_id: str,
        messages: list[Content],
        principal_scope: PrincipalScope | None,
    ) -> None:
        self._stream = stream
        self._runtime = runtime
        self._context_id = context_id
        self._messages = messages
        self._principal_scope = principal_scope
        self._text_deltas: list[str] = []
        self._tool_calls: list[ToolCall] = []
        self._persisted = False

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ChatStreamEvent]:
        try:
            async for event in self._stream:
                self._accumulate_assistant_event(event)
                yield event
        finally:
            await self._persist_context_messages()

    async def _persist_context_messages(self) -> None:
        if self._persisted:
            return

        self._persisted = True
        for message in self._messages:
            await self._runtime.contexts.append(
                self._context_id,
                message,
                principal_scope=self._principal_scope,
            )
        assistant_message = self._assistant_message()
        if assistant_message is not None:
            await self._runtime.contexts.append(
                self._context_id,
                assistant_message,
                principal_scope=self._principal_scope,
            )

    def _accumulate_assistant_event(self, event: ChatStreamEvent) -> None:
        if event.event_type is ChatStreamEventType.MESSAGE_DELTA:
            text = event.text_delta
            if text is None and event.content_part is not None:
                text = event.content_part.text
            if text:
                self._text_deltas.append(text)

        if (
            event.event_type is ChatStreamEventType.TOOL_CALL_COMPLETED
            and event.tool_call is not None
        ):
            self._tool_calls.append(event.tool_call)

    def _assistant_message(self) -> Content | None:
        text = "".join(self._text_deltas)
        content = (
            [ContentPart(type=ContentPartType.TEXT, text=text)]
            if text
            else None
        )
        tool_calls = self._tool_calls or None
        if content is None and tool_calls is None:
            return None

        return Content(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
        )
