from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    ManageProtocol,
    RegisterProtocol,
    ResponsibilityProtocol,
)
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

    def register(self, memory: MemoryItem) -> None: ...

    def unregister(self, memory_id: str) -> None: ...

    def get(self, memory_id: str) -> MemoryItem: ...

    def has(self, memory_id: str) -> bool: ...

    def list_memories(self) -> list[MemoryItem]: ...


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


class MemoryManageProtocol(MemoryProtocol, ManageProtocol):
    """
    记忆管理协议
    """

    async def create(self, memory: MemoryItem) -> MemoryItem: ...

    async def get(self, memory_id: str) -> MemoryItem: ...

    async def list_memories(self) -> list[MemoryItem]: ...

    async def delete(self, memory_id: str) -> None: ...

    async def clear(self) -> None: ...
