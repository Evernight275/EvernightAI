from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from EvernightAI.core.domain.memory import MemoryRegister
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.memory import (
    MemoryItem,
    MemoryQuery,
    MemoryScope,
    MemoryScopeSelector,
)
from EvernightAI.infra.adapters.memory.sqlite import SQLiteMemoryRegister


def make_memory(
    memory_id: str,
    *,
    content: str,
    owner_id: str | None = "owner-1",
    scope: MemoryScope = MemoryScope.USER,
    scope_id: str | None = "user-1",
    priority: int = 0,
    relevance: float = 0.0,
    confidence: float = 1.0,
    tags: list[str] | None = None,
    is_enabled: bool = True,
    expires_at: datetime | None = None,
) -> MemoryItem:
    return MemoryItem(
        memory_id=memory_id,
        owner_id=owner_id,
        content=content,
        scope=scope,
        scope_id=scope_id,
        priority=priority,
        relevance=relevance,
        confidence=confidence,
        tags=tags or [],
        is_enabled=is_enabled,
        expires_at=expires_at,
    )


@contextmanager
def memory_register(kind: str, tmp_path: Path) -> Iterator[MemoryRegister | SQLiteMemoryRegister]:
    if kind == "memory":
        yield MemoryRegister()
        return

    register = SQLiteMemoryRegister(tmp_path / "memories.sqlite3")
    try:
        yield register
    finally:
        register.close()


@pytest.mark.parametrize("register_kind", ["memory", "sqlite"])
def test_memory_register_query_contract_matches_across_adapters(
    register_kind: str,
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc)
    memories = [
        make_memory(
            "mem-best",
            content="Same fact",
            priority=10,
            relevance=0.9,
            confidence=0.9,
            tags=["Profile", "Style"],
        ),
        make_memory(
            "mem-duplicate",
            content=" same fact ",
            priority=9,
            relevance=0.8,
            confidence=0.9,
            tags=["style"],
        ),
        make_memory(
            "mem-other-owner",
            content="Other owner",
            owner_id="owner-2",
            priority=100,
            relevance=1.0,
            tags=["style"],
        ),
        make_memory(
            "mem-expired",
            content="Expired",
            priority=100,
            relevance=1.0,
            tags=["style"],
            expires_at=now - timedelta(minutes=1),
        ),
        make_memory(
            "mem-disabled",
            content="Disabled",
            priority=100,
            relevance=1.0,
            tags=["style"],
            is_enabled=False,
        ),
        make_memory(
            "mem-global",
            content="Global",
            owner_id=None,
            scope=MemoryScope.GLOBAL,
            scope_id=None,
            priority=8,
            relevance=0.7,
            tags=["style"],
        ),
    ]

    with memory_register(register_kind, tmp_path) as register:
        for memory in memories:
            register.register(memory)

        query = MemoryQuery(
            text="same fact",
            scopes=[
                MemoryScopeSelector(scope=MemoryScope.USER, scope_id="user-1"),
                MemoryScopeSelector(scope=MemoryScope.GLOBAL),
            ],
            tags=[" STYLE "],
            minimum_relevance=0.5,
            deduplicate=True,
            limit=2,
        )

        selected = register.list_memories(owner_id="owner-1", query=query)
        limited = register.list_memories(owner_id="owner-1", query=query, limit=1)
        scoped = register.list_memories(
            query=query,
            principal_scope=PrincipalScope(owner_id="owner-1"),
        )
        blocked = register.list_memories(
            owner_id="owner-2",
            principal_scope=PrincipalScope(owner_id="owner-1"),
        )

    assert [memory.memory_id for memory in selected] == ["mem-best"]
    assert [memory.memory_id for memory in limited] == ["mem-best"]
    assert [memory.memory_id for memory in scoped] == ["mem-best"]
    assert blocked == []
