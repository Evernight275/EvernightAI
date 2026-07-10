from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    ManageProtocol,
    RegisterProtocol,
    ResponsibilityProtocol,
)
from EvernightAI.core.schema.content import ChatRequest, Content
from EvernightAI.core.schema.context import Context, ContextWindow
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.memory import MemorySelection
from EvernightAI.core.schema.tool import ToolDefinition
from EvernightAI.core.error.context import ContextStateError


class ContextProtocol(EvernightAIProtocol):
    """
    上下文协议
    """

    ...


class ContextRegisterProtocol(ContextProtocol, RegisterProtocol):
    """
    上下文注册协议
    """

    def register(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    def unregister(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    def get(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context: ...

    def has(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> bool: ...

    def list_contexts(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[Context]: ...

    def append_message(
        self,
        context_id: str,
        message: Content,
        *,
        expected_revision: int | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> Context:
        context = self.get(context_id, principal_scope=principal_scope)
        if expected_revision is not None and context.revision != expected_revision:
            raise ContextStateError(
                f"The context {context_id} revision is {context.revision}, "
                f"expected {expected_revision}"
            )
        updated = context.model_copy(
            update={
                "messages": [*context.messages, message],
                "revision": context.revision + 1,
            }
        )
        self.register(updated, principal_scope=principal_scope)
        return updated


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


class ContextStrategyProtocol(ContextResponsibilityProtocol):
    """
    上下文策略协议
    """

    def compose_chat_request(
        self,
        context: Context,
        *,
        model_id: str,
        messages: list[Content] | None = None,
        memory_selection: MemorySelection | None = None,
        tools: list[ToolDefinition] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatRequest: ...


class ContextTokenEstimatorProtocol(ContextResponsibilityProtocol):
    def estimate(self, message: Content) -> int: ...


class ContextSummarizerProtocol(ContextResponsibilityProtocol):
    def summarize(self, messages: list[Content]) -> Content: ...


class ContextManageProtocol(ContextProtocol, ManageProtocol):
    """
    上下文管理协议
    """

    async def create(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context: ...

    async def get(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context: ...

    async def append(
        self,
        context_id: str,
        message: Content,
        *,
        expected_revision: int | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> Context: ...

    async def replace(
        self,
        context: Context,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Context: ...

    async def list_contexts(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[Context]: ...

    async def delete(
        self,
        context_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    async def clear(
        self,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...
