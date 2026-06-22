from pathlib import Path

import pytest

from EvernightAI.core.domain.context import ContextManager
from EvernightAI.core.error.context import ContextNotFoundError
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.infra.adapters.context.sqlite import SQLiteContextRegister
from EvernightAI.bootstrap.runtime import (
    create_sqlite_context_manager,
    create_sqlite_context_register,
)


def make_message(text: str) -> Content:
    return Content(
        role=MessageRole.USER,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def make_database_path(tmp_path: Path) -> Path:
    return tmp_path / "contexts.sqlite3"


def test_sqlite_context_register_persists_contexts(tmp_path: Path) -> None:
    database_path = make_database_path(tmp_path)
    context = Context(
        context_id="ctx-1",
        messages=[make_message("Hello")],
        metadata={"source": "sqlite"},
    )

    register = SQLiteContextRegister(database_path)
    register.register(context)
    register.close()

    reopened = SQLiteContextRegister(database_path)

    try:
        assert reopened.has("ctx-1") is True
        assert reopened.get("ctx-1") == context
        assert reopened.list_contexts() == [context]
    finally:
        reopened.close()


def test_sqlite_context_register_raises_for_missing_context(tmp_path: Path) -> None:
    register = SQLiteContextRegister(make_database_path(tmp_path))

    try:
        with pytest.raises(ContextNotFoundError):
            register.get("missing")

        with pytest.raises(ContextNotFoundError):
            register.unregister("missing")
    finally:
        register.close()


@pytest.mark.asyncio
async def test_sqlite_context_manager_appends_and_deletes(
    tmp_path: Path,
) -> None:
    register = SQLiteContextRegister(make_database_path(tmp_path))
    manager = ContextManager(register)

    try:
        await manager.create(Context(context_id="ctx-1"))
        updated = await manager.append("ctx-1", make_message("Hello"))

        assert updated.messages == [make_message("Hello")]
        assert await manager.get("ctx-1") == updated

        await manager.delete("ctx-1")

        assert await manager.list_contexts() == []
    finally:
        register.close()


def test_sqlite_context_bootstrap_helpers(tmp_path: Path) -> None:
    database_path = make_database_path(tmp_path)
    register = create_sqlite_context_register(database_path)

    try:
        assert isinstance(register, SQLiteContextRegister)
    finally:
        register.close()

    manager = create_sqlite_context_manager(database_path)

    assert isinstance(manager, ContextManager)
