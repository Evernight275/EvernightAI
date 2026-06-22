from pathlib import Path

import pytest

from EvernightAI.core.domain.memory import MemoryManager
from EvernightAI.core.error.memory import MemoryNotFoundError
from EvernightAI.core.schema.memory import MemoryItem, MemoryKind, MemoryScope
from EvernightAI.infra.adapters.memory.sqlite import SQLiteMemoryRegister
from EvernightAI.bootstrap.runtime import (
    create_sqlite_memory_manager,
    create_sqlite_memory_register,
)


def make_database_path(tmp_path: Path) -> Path:
    return tmp_path / "memories.sqlite3"


def make_memory(memory_id: str = "mem-1") -> MemoryItem:
    return MemoryItem(
        memory_id=memory_id,
        content="Prefer concise answers",
        kind=MemoryKind.PREFERENCE,
        scope=MemoryScope.USER,
        scope_id="user-1",
        tags=["style", "answer"],
        priority=10,
        metadata={"source": "sqlite"},
    )


def test_sqlite_memory_register_persists_memories(tmp_path: Path) -> None:
    database_path = make_database_path(tmp_path)
    memory = make_memory()

    register = SQLiteMemoryRegister(database_path)
    register.register(memory)
    register.close()

    reopened = SQLiteMemoryRegister(database_path)

    try:
        assert reopened.has("mem-1") is True
        assert reopened.get("mem-1") == memory
        assert reopened.list_memories() == [memory]

        updated = memory.model_copy(update={"content": "Prefer short answers"})
        reopened.register(updated)

        assert reopened.get("mem-1").content == "Prefer short answers"
    finally:
        reopened.close()


def test_sqlite_memory_register_raises_for_missing_memory(tmp_path: Path) -> None:
    register = SQLiteMemoryRegister(make_database_path(tmp_path))

    try:
        with pytest.raises(MemoryNotFoundError):
            register.get("missing")

        with pytest.raises(MemoryNotFoundError):
            register.unregister("missing")
    finally:
        register.close()


@pytest.mark.asyncio
async def test_sqlite_memory_manager_creates_and_deletes(
    tmp_path: Path,
) -> None:
    register = SQLiteMemoryRegister(make_database_path(tmp_path))
    manager = MemoryManager(register)

    try:
        created = await manager.create(make_memory())

        assert await manager.get("mem-1") == created
        assert await manager.list_memories() == [created]

        await manager.delete("mem-1")

        assert await manager.list_memories() == []
    finally:
        register.close()


def test_sqlite_memory_bootstrap_helpers(tmp_path: Path) -> None:
    database_path = make_database_path(tmp_path)
    register = create_sqlite_memory_register(database_path)

    try:
        assert isinstance(register, SQLiteMemoryRegister)
    finally:
        register.close()

    manager = create_sqlite_memory_manager(database_path)

    assert isinstance(manager, MemoryManager)
