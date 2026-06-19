from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    ManageProtocol,
    RegisterProtocol,
    ResponsibilityProtocol,
)
from EvernightAI.core.schema.content import ChatRequest, Content
from EvernightAI.core.schema.context import Context, ContextWindow
from EvernightAI.core.schema.tool import ToolDefinition


class ContextProtocol(EvernightAIProtocol):
    """
    上下文协议
    """

    ...


class ContextRegisterProtocol(ContextProtocol, RegisterProtocol):
    """
    上下文注册协议
    """

    def register(self, context: Context) -> None: ...

    def unregister(self, context_id: str) -> None: ...

    def get(self, context_id: str) -> Context: ...

    def has(self, context_id: str) -> bool: ...

    def list_contexts(self) -> list[Context]: ...


class ContextResponsibilityProtocol(ContextProtocol, ResponsibilityProtocol):
    """
    上下文职责协议
    """


class ContextOrganizerProtocol(ContextResponsibilityProtocol):
    """
    上下文组织协议
    """

    def organize(
        self,
        context: Context,
        *,
        messages: list[Content] | None = None,
    ) -> ContextWindow: ...

    def to_chat_request(
        self,
        context: Context,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest: ...


class ContextManageProtocol(ContextProtocol, ManageProtocol):
    """
    上下文管理协议
    """

    async def create(self, context: Context) -> Context: ...

    async def get(self, context_id: str) -> Context: ...

    async def append(self, context_id: str, message: Content) -> Context: ...

    async def replace(self, context: Context) -> Context: ...

    async def list_contexts(self) -> list[Context]: ...

    async def delete(self, context_id: str) -> None: ...

    async def clear(self) -> None: ...
