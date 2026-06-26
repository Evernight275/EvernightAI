from EvernightAI.core.error.context import ContextNotFoundError
from EvernightAI.core.protocol.context import (
    ContextOrganizerProtocol,
    ContextStrategyProtocol,
    ContextManageProtocol,
    ContextRegisterProtocol,
)
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageStatus,
    MessageRole,
)
from EvernightAI.core.schema.context import Context, ContextWindow
from EvernightAI.core.schema.memory import MemorySelection
from EvernightAI.core.schema.tool import ToolDefinition


class ContextRegister(ContextRegisterProtocol):
    def __init__(self) -> None:
        self._contexts: dict[str, Context] = {}

    def register(self, context: Context) -> None:
        """注册上下文"""
        self._contexts[context.context_id] = context

    def unregister(self, context_id: str) -> None:
        """注销上下文"""
        if not self.has(context_id):
            raise ContextNotFoundError(f"The context {context_id} is not registered")

        self._contexts.pop(context_id, None)

    def get(self, context_id: str) -> Context:
        """获取上下文"""
        if self.has(context_id):
            return self._contexts[context_id]

        raise ContextNotFoundError(f"The context {context_id} is not found")

    def has(self, context_id: str) -> bool:
        """检查上下文是否存在"""
        return context_id in self._contexts

    def list_contexts(self) -> list[Context]:
        """列出所有上下文"""
        return list(self._contexts.values())


class ContextManager(ContextManageProtocol):
    def __init__(self, register: ContextRegisterProtocol) -> None:
        self._register = register

    async def create(self, context: Context) -> Context:
        """创建上下文"""
        self._register.register(context)
        return self._register.get(context.context_id)

    async def get(self, context_id: str) -> Context:
        """获取上下文"""
        return self._register.get(context_id)

    async def append(self, context_id: str, message: Content) -> Context:
        """追加上下文消息"""
        context = self._register.get(context_id)
        updated = context.model_copy(
            update={"messages": [*context.messages, message]},
        )
        self._register.register(updated)
        return updated

    async def replace(self, context: Context) -> Context:
        """替换上下文"""
        if not self._register.has(context.context_id):
            raise ContextNotFoundError(f"The context {context.context_id} is not found")

        self._register.register(context)
        return self._register.get(context.context_id)

    async def list_contexts(self) -> list[Context]:
        """列出所有上下文"""
        return self._register.list_contexts()

    async def delete(self, context_id: str) -> None:
        """删除上下文"""
        self._register.unregister(context_id)

    async def clear(self) -> None:
        """清空上下文"""
        for context in list(self._register.list_contexts()):
            self._register.unregister(context.context_id)


class ContextOrganizer(ContextOrganizerProtocol):
    def organize(
        self,
        context: Context,
        *,
        messages: list[Content] | None = None,
    ) -> ContextWindow:
        """组织基础上下文窗口"""
        next_messages = messages or []
        return ContextWindow(
            context_id=context.context_id,
            messages=[
                *self._active_messages(context.messages),
                *self._active_messages(next_messages),
            ],
            metadata=dict(context.metadata),
        )

    def to_chat_request(
        self,
        context: Context,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest:
        """将基础上下文组织为聊天请求"""
        window = self.organize(context, messages=messages)
        return ChatRequest(
            model_id=model_id,
            messages=window.messages,
            tools=tools,
            metadata={
                **window.metadata,
                **(metadata or {}),
                "context_id": window.context_id,
            },
        )

    def _active_messages(self, messages: list[Content]) -> list[Content]:
        return [
            message
            for message in messages
            if message.status in {None, MessageStatus.ACTIVE}
        ]


class BasicContextStrategy(ContextStrategyProtocol):
    def __init__(self, organizer: ContextOrganizerProtocol) -> None:
        self._organizer = organizer

    def compose_chat_request(
        self,
        context: Context,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        memory_selection: MemorySelection | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest:
        """组合基础聊天请求"""
        next_messages = list(messages or [])
        request_metadata: dict[str, object] = dict(metadata or {})

        if memory_selection is not None:
            memory_message = self._compose_memory_message(memory_selection)
            if memory_message is not None:
                next_messages = [memory_message, *next_messages]
            request_metadata["memory_ids"] = [
                memory.memory_id for memory in memory_selection.memories
            ]
            request_metadata["memory_selection"] = dict(memory_selection.metadata)

        return self._organizer.to_chat_request(
            context,
            model_id=model_id,
            messages=next_messages,
            tools=tools,
            metadata=request_metadata,
        )

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
