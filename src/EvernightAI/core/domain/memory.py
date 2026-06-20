from EvernightAI.core.error.memory import MemoryNotFoundError
from EvernightAI.core.protocol.memory import (
    MemoryManageProtocol,
    MemoryRegisterProtocol,
    MemoryStrategyProtocol,
)
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery, MemorySelection


class MemoryRegister(MemoryRegisterProtocol):
    def __init__(self) -> None:
        self._memories: dict[str, MemoryItem] = {}

    def register(self, memory: MemoryItem) -> None:
        """注册记忆"""
        self._memories[memory.memory_id] = memory

    def unregister(self, memory_id: str) -> None:
        """注销记忆"""
        if not self.has(memory_id):
            raise MemoryNotFoundError(f"The memory {memory_id} is not registered")

        self._memories.pop(memory_id, None)

    def get(self, memory_id: str) -> MemoryItem:
        """获取记忆"""
        if self.has(memory_id):
            return self._memories[memory_id]

        raise MemoryNotFoundError(f"The memory {memory_id} is not found")

    def has(self, memory_id: str) -> bool:
        """检查记忆是否存在"""
        return memory_id in self._memories

    def list_memories(self) -> list[MemoryItem]:
        """列出所有记忆"""
        return list(self._memories.values())


class MemoryManager(MemoryManageProtocol):
    def __init__(self, register: MemoryRegisterProtocol) -> None:
        self._register = register

    async def create(self, memory: MemoryItem) -> MemoryItem:
        """创建记忆"""
        self._register.register(memory)
        return self._register.get(memory.memory_id)

    async def get(self, memory_id: str) -> MemoryItem:
        """获取记忆"""
        return self._register.get(memory_id)

    async def list_memories(self) -> list[MemoryItem]:
        """列出所有记忆"""
        return self._register.list_memories()

    async def delete(self, memory_id: str) -> None:
        """删除记忆"""
        self._register.unregister(memory_id)

    async def clear(self) -> None:
        """清空记忆"""
        for memory in list(self._register.list_memories()):
            self._register.unregister(memory.memory_id)


class BasicMemoryStrategy(MemoryStrategyProtocol):
    def select(
        self,
        memories: list[MemoryItem],
        query: MemoryQuery | None = None,
    ) -> MemorySelection:
        """按基础条件选择记忆"""
        query = query or MemoryQuery()
        selected = [
            memory
            for memory in memories
            if self._matches(memory, query)
        ]
        selected.sort(
            key=lambda memory: (
                -memory.priority,
                memory.memory_id,
            )
        )

        if query.limit is not None:
            selected = selected[: query.limit]

        return MemorySelection(
            memories=selected,
            metadata={
                "strategy": self.__class__.__name__,
                "total_candidates": len(memories),
                "selected_count": len(selected),
            },
        )

    def _matches(self, memory: MemoryItem, query: MemoryQuery) -> bool:
        if not memory.is_enabled:
            return False
        if query.scope is not None and memory.scope is not query.scope:
            return False
        if query.scope_id is not None and memory.scope_id != query.scope_id:
            return False
        if query.kinds and memory.kind not in query.kinds:
            return False
        if query.tags and not set(query.tags).issubset(memory.tags):
            return False

        return True
