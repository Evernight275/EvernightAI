from EvernightAI.core.error.context import ContextNotFoundError
from EvernightAI.core.protocol.context import (
    ContextOrganizerProtocol,
    ContextManageProtocol,
    ContextRegisterProtocol,
)
from EvernightAI.core.schema.content import ChatRequest, Content
from EvernightAI.core.schema.context import Context, ContextWindow
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
            messages=[*context.messages, *next_messages],
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
