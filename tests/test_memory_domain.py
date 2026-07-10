import pytest
from datetime import datetime, timedelta, timezone

from EvernightAI.core.domain.memory import (
    BasicMemoryStrategy,
    BasicMemoryWriteStrategy,
    MemoryManager,
    MemoryRegister,
)
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunResult
from EvernightAI.core.schema.content import (
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
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
async def test_memory_manager_updates_existing_memory_timestamp() -> None:
    manager = MemoryManager(MemoryRegister())
    original = make_memory("mem-1", content="old")
    await manager.create(original)

    updated = await manager.replace(original.model_copy(update={"content": "new"}))

    assert updated.content == "new"
    assert updated.updated_at >= original.updated_at


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


def test_basic_memory_strategy_filters_expired_low_confidence_and_duplicates() -> None:
    strategy = BasicMemoryStrategy()
    memories = [
        make_memory("best", content="Same").model_copy(
            update={"relevance": 0.9, "confidence": 0.9}
        ),
        make_memory("duplicate", content=" same ").model_copy(
            update={"relevance": 0.8, "confidence": 0.9}
        ),
        make_memory("low-confidence", content="Other").model_copy(
            update={"relevance": 1.0, "confidence": 0.2}
        ),
        make_memory("expired", content="Expired").model_copy(
            update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
        ),
    ]

    selection = strategy.select(
        memories,
        MemoryQuery(
            minimum_relevance=0.5,
            minimum_confidence=0.5,
            deduplicate=True,
        ),
    )

    assert [memory.memory_id for memory in selection.memories] == ["best"]


def test_basic_memory_write_strategy_creates_context_summary_when_enabled() -> None:
    strategy = BasicMemoryWriteStrategy()
    request = AgentRunRequest(
        provider_id="provider-1",
        context_id="ctx-1",
        model_id="model-1",
        messages=[
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="Remember this")],
            )
        ],
        write_memory=True,
    )
    result = AgentRunResult(
        response=ChatResponse(
            model_id="model-1",
            message=Content(
                role=MessageRole.ASSISTANT,
                content=[ContentPart(type=ContentPartType.TEXT, text="Stored")],
            ),
        )
    )

    memories = strategy.create_memories(request, result)

    assert len(memories) == 1
    assert memories[0].kind is MemoryKind.SUMMARY
    assert memories[0].scope is MemoryScope.CONTEXT
    assert memories[0].scope_id == "ctx-1"
    assert memories[0].tags == ["agent", "summary"]
    assert "Remember this" in memories[0].content
    assert "Stored" in memories[0].content
    assert memories[0].metadata == {
        "provider_id": "provider-1",
        "model_id": "model-1",
        "stop_reason": "finished",
        "step_count": 0,
    }


def test_basic_memory_write_strategy_creates_session_summary_when_session_id_present() -> None:
    strategy = BasicMemoryWriteStrategy()
    request = AgentRunRequest(
        provider_id="provider-1",
        context_id="ctx-1",
        model_id="model-1",
        messages=[
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="Remember this")],
            )
        ],
        write_memory=True,
        metadata={"session_id": "session-1"},
    )
    result = AgentRunResult(
        response=ChatResponse(
            model_id="model-1",
            message=Content(
                role=MessageRole.ASSISTANT,
                content=[ContentPart(type=ContentPartType.TEXT, text="Stored")],
            ),
        )
    )

    memories = strategy.create_memories(request, result)

    assert len(memories) == 1
    assert memories[0].scope is MemoryScope.SESSION
    assert memories[0].scope_id == "session-1"
    assert memories[0].tags == ["agent", "summary", "session"]
    assert memories[0].metadata == {
        "provider_id": "provider-1",
        "model_id": "model-1",
        "stop_reason": "finished",
        "step_count": 0,
        "context_id": "ctx-1",
    }


def test_basic_memory_write_strategy_skips_when_disabled() -> None:
    strategy = BasicMemoryWriteStrategy()

    memories = strategy.create_memories(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
        ),
        AgentRunResult(
            response=ChatResponse(
                model_id="model-1",
                message=Content(role=MessageRole.ASSISTANT),
            )
        ),
    )

    assert memories == []


def test_basic_memory_write_strategy_skips_empty_text_content() -> None:
    strategy = BasicMemoryWriteStrategy()

    memories = strategy.create_memories(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[Content(role=MessageRole.USER)],
            write_memory=True,
        ),
        AgentRunResult(
            response=ChatResponse(
                model_id="model-1",
                message=Content(role=MessageRole.ASSISTANT),
            )
        ),
    )

    assert memories == []


def test_basic_memory_write_strategy_ignores_non_text_parts() -> None:
    strategy = BasicMemoryWriteStrategy()

    memories = strategy.create_memories(
        AgentRunRequest(
            provider_id="provider-1",
            context_id="ctx-1",
            model_id="model-1",
            messages=[
                Content(
                    role=MessageRole.USER,
                    content=[
                        ContentPart(
                            type=ContentPartType.IMAGE,
                            url="https://example.com/image.png",
                        ),
                        ContentPart(type=ContentPartType.TEXT, text="Keep this"),
                    ],
                )
            ],
            write_memory=True,
        ),
        AgentRunResult(
            response=ChatResponse(
                model_id="model-1",
                message=Content(
                    role=MessageRole.ASSISTANT,
                    content=[
                        ContentPart(type=ContentPartType.TEXT, text="Got it"),
                    ],
                ),
            )
        ),
    )

    assert len(memories) == 1
    assert "Keep this" in memories[0].content
    assert "https://example.com/image.png" not in memories[0].content
