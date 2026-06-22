from pathlib import Path

import pytest

from EvernightAI.bootstrap.runtime import (
    create_sqlite_session_manager,
    create_sqlite_session_register,
)
from EvernightAI.core.domain.session import SessionManager
from EvernightAI.core.error.session import SessionNotFoundError
from EvernightAI.core.schema.session import Session, SessionStatus
from EvernightAI.infra.adapters.session.sqlite import SQLiteSessionRegister


def make_database_path(tmp_path: Path) -> Path:
    return tmp_path / "sessions.sqlite3"


def test_sqlite_session_register_persists_sessions(tmp_path: Path) -> None:
    database_path = make_database_path(tmp_path)
    session = Session(
        session_id="session-1",
        title="Chat",
        context_id="ctx-1",
        provider_id="provider-1",
        model_id="model-1",
        metadata={"source": "sqlite"},
    )

    register = SQLiteSessionRegister(database_path)
    register.register(session)
    register.close()

    reopened = SQLiteSessionRegister(database_path)

    try:
        assert reopened.has("session-1") is True
        assert reopened.get("session-1") == session
        assert reopened.list_sessions() == [session]
    finally:
        reopened.close()


def test_sqlite_session_register_raises_for_missing_session(tmp_path: Path) -> None:
    register = SQLiteSessionRegister(make_database_path(tmp_path))

    try:
        with pytest.raises(SessionNotFoundError):
            register.get("missing")

        with pytest.raises(SessionNotFoundError):
            register.unregister("missing")
    finally:
        register.close()


@pytest.mark.asyncio
async def test_sqlite_session_manager_archives_and_deletes(tmp_path: Path) -> None:
    register = SQLiteSessionRegister(make_database_path(tmp_path))
    manager = SessionManager(register)

    try:
        await manager.create(Session(session_id="session-1", context_id="ctx-1"))
        archived = await manager.archive("session-1")

        assert archived.status is SessionStatus.ARCHIVED
        assert await manager.get("session-1") == archived

        await manager.delete("session-1")

        assert await manager.list_sessions() == []
    finally:
        register.close()


def test_sqlite_session_bootstrap_helpers(tmp_path: Path) -> None:
    database_path = make_database_path(tmp_path)
    register = create_sqlite_session_register(database_path)

    try:
        assert isinstance(register, SQLiteSessionRegister)
    finally:
        register.close()

    manager = create_sqlite_session_manager(database_path)

    assert isinstance(manager, SessionManager)
