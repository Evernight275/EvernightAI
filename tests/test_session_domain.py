from datetime import datetime, timezone

import pytest

from EvernightAI.core.domain.session import SessionManager, SessionRegister
from EvernightAI.core.error.session import SessionNotFoundError
from EvernightAI.core.schema.session import Session, SessionStatus


def make_session(
    session_id: str,
    *,
    context_id: str = "ctx-1",
    title: str | None = "Chat",
    provider_id: str | None = "provider-1",
    model_id: str | None = "model-1",
    status: SessionStatus = SessionStatus.ACTIVE,
) -> Session:
    return Session(
        session_id=session_id,
        title=title,
        context_id=context_id,
        provider_id=provider_id,
        model_id=model_id,
        status=status,
    )


def test_session_register_stores_sessions() -> None:
    register = SessionRegister()
    session = make_session("session-1")

    register.register(session)

    assert register.has("session-1") is True
    assert register.get("session-1") == session
    assert register.list_sessions() == [session]


def test_session_register_raises_for_missing_session() -> None:
    register = SessionRegister()

    with pytest.raises(SessionNotFoundError):
        register.get("missing")

    with pytest.raises(SessionNotFoundError):
        register.unregister("missing")


@pytest.mark.asyncio
async def test_session_manager_creates_replaces_archives_and_deletes() -> None:
    manager = SessionManager(SessionRegister())
    session = make_session("session-1")

    created = await manager.create(session)
    replacement = session.model_copy(update={"title": "Renamed"})
    replaced = await manager.replace(replacement)
    archived = await manager.archive("session-1")

    assert created == session
    assert replaced.title == "Renamed"
    assert archived.status is SessionStatus.ARCHIVED
    assert archived.updated_at >= replaced.updated_at
    assert await manager.get("session-1") == archived

    await manager.delete("session-1")

    assert await manager.list_sessions() == []


@pytest.mark.asyncio
async def test_session_manager_clear_removes_all_sessions() -> None:
    manager = SessionManager(SessionRegister())
    await manager.create(make_session("session-1"))
    await manager.create(make_session("session-2"))

    await manager.clear()

    assert await manager.list_sessions() == []


def test_session_defaults_create_timezone_aware_timestamps() -> None:
    session = Session(session_id="session-1", context_id="ctx-1")

    assert isinstance(session.created_at, datetime)
    assert session.created_at.tzinfo is timezone.utc
    assert session.updated_at.tzinfo is timezone.utc
    assert session.status is SessionStatus.ACTIVE
