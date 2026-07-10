from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    ManageProtocol,
    RegisterProtocol,
    ResponsibilityProtocol,
)
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunResult
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery, MemorySelection


class MemoryProtocol(EvernightAIProtocol):
    """
    记忆协议
    """

    ...


class MemoryRegisterProtocol(MemoryProtocol, RegisterProtocol):
    """
    记忆注册协议
    """

    def register(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    def unregister(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    def get(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem: ...

    def has(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> bool: ...

    def list_memories(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        query: MemoryQuery | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[MemoryItem]: ...


class MemoryResponsibilityProtocol(MemoryProtocol, ResponsibilityProtocol):
    """
    记忆职责协议
    """


class MemoryStrategyProtocol(MemoryResponsibilityProtocol):
    """
    记忆选择策略协议
    """

    def select(
        self,
        memories: list[MemoryItem],
        query: MemoryQuery | None = None,
    ) -> MemorySelection: ...


class MemoryWriteStrategyProtocol(MemoryResponsibilityProtocol):
    """
    记忆写入策略协议
    """

    def create_memories(
        self,
        request: AgentRunRequest,
        result: AgentRunResult,
    ) -> list[MemoryItem]: ...


class MemoryManageProtocol(MemoryProtocol, ManageProtocol):
    """
    记忆管理协议
    """

    async def create(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem: ...

    async def get(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem: ...

    async def replace(
        self,
        memory: MemoryItem,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> MemoryItem: ...

    async def list_memories(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        query: MemoryQuery | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[MemoryItem]: ...

    async def delete(
        self,
        memory_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    async def clear(
        self,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...
