import pytest

from EvernightAI.application.session import SessionApplication
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.session import Session


@pytest.mark.asyncio
async def test_session_application_creates_context_for_session() -> None:
    runtime = create_runtime()
    app = SessionApplication(runtime)

    session = await app.create_session(
        Session(
            session_id="session-1",
            title="First chat",
            context_id="ctx-1",
        )
    )

    context = await runtime.contexts.get("ctx-1")

    assert session.context_id == "ctx-1"
    assert context.context_id == "ctx-1"
    assert context.messages == []
    assert context.metadata == {"session_id": "session-1"}


@pytest.mark.asyncio
async def test_session_application_reuses_existing_context() -> None:
    runtime = create_runtime()
    app = SessionApplication(runtime)
    existing_context = Context(
        context_id="ctx-1",
        messages=[
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="Stored")]
            )
        ],
        metadata={"source": "existing"},
    )
    await runtime.contexts.create(existing_context)

    await app.create_session(
        Session(
            session_id="session-1",
            title="First chat",
            context_id="ctx-1",
        )
    )

    context = await runtime.contexts.get("ctx-1")

    assert context == existing_context


@pytest.mark.asyncio
async def test_session_application_creates_context_when_replacing_session() -> None:
    runtime = create_runtime()
    app = SessionApplication(runtime)
    await app.create_session(
        Session(
            session_id="session-1",
            title="First chat",
            context_id="ctx-1",
        )
    )

    replaced = await app.replace_session(
        Session(
            session_id="session-1",
            title="Moved chat",
            context_id="ctx-2",
        )
    )

    context = await runtime.contexts.get("ctx-2")

    assert replaced.context_id == "ctx-2"
    assert context.metadata == {"session_id": "session-1"}
