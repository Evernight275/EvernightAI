import pytest

from EvernightAI.core.domain.memory import (
    BasicMemoryStrategy,
    MemoryManager,
    MemoryRegister,
)
from EvernightAI.core.error.memory import MemoryNotFoundError
from EvernightAI.core.schema.memory import (
    MemoryItem,
    MemoryKind,
    MemoryQuery,
    MemoryScope,
)


def make_memory(
    memory_id: str,
    *,
    content: str = "memory",
    kind: MemoryKind = MemoryKind.FACT,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    tags: list[str] | None = None,
    priority: int = 0,
    is_enabled: bool = True,
) -> MemoryItem:
    return MemoryItem(
        memory_id=memory_id,
        content=content,
        kind=kind,
        scope=scope,
        scope_id=scope_id,
        tags=tags or [],
        priority=priority,
        is_enabled=is_enabled,
    )


def test_memory_register_stores_memories() -> None:
    register = MemoryRegister()
    memory = make_memory("mem-1", content="Use concise replies")

    register.register(memory)

    assert register.has("mem-1") is True
    assert register.get("mem-1") == memory
    assert register.list_memories() == [memory]


def test_memory_register_raises_for_missing_memory() -> None:
    register = MemoryRegister()

    with pytest.raises(MemoryNotFoundError):
        register.get("missing")

    with pytest.raises(MemoryNotFoundError):
        register.unregister("missing")


@pytest.mark.asyncio
async def test_memory_manager_creates_and_deletes_memories() -> None:
    manager = MemoryManager(MemoryRegister())
    memory = make_memory("mem-1")

    created = await manager.create(memory)

    assert created == memory
    assert await manager.list_memories() == [memory]

    await manager.delete("mem-1")

    assert await manager.list_memories() == []


@pytest.mark.asyncio
async def test_memory_manager_clears_memories() -> None:
    manager = MemoryManager(MemoryRegister())
    await manager.create(make_memory("mem-1"))
    await manager.create(make_memory("mem-2"))

    await manager.clear()

    assert await manager.list_memories() == []


def test_basic_memory_strategy_filters_disabled_scope_kind_and_tags() -> None:
    strategy = BasicMemoryStrategy()
    memories = [
        make_memory(
            "global-fact",
            scope=MemoryScope.GLOBAL,
            kind=MemoryKind.FACT,
            tags=["profile"],
        ),
        make_memory(
            "user-preference",
            scope=MemoryScope.USER,
            scope_id="user-1",
            kind=MemoryKind.PREFERENCE,
            tags=["profile", "style"],
        ),
        make_memory(
            "disabled",
            scope=MemoryScope.USER,
            scope_id="user-1",
            kind=MemoryKind.PREFERENCE,
            tags=["profile", "style"],
            is_enabled=False,
        ),
    ]

    selection = strategy.select(
        memories,
        MemoryQuery(
            scope=MemoryScope.USER,
            scope_id="user-1",
            kinds=[MemoryKind.PREFERENCE],
            tags=["style"],
        ),
    )

    assert selection.memories == [memories[1]]
    assert selection.metadata["selected_count"] == 1


def test_basic_memory_strategy_sorts_by_priority_and_limits() -> None:
    strategy = BasicMemoryStrategy()
    memories = [
        make_memory("low", priority=1),
        make_memory("high-b", priority=10),
        make_memory("high-a", priority=10),
    ]

    selection = strategy.select(memories, MemoryQuery(limit=2))

    assert [memory.memory_id for memory in selection.memories] == [
        "high-a",
        "high-b",
    ]
    assert selection.metadata == {
        "strategy": "BasicMemoryStrategy",
        "total_candidates": 3,
        "selected_count": 2,
    }
