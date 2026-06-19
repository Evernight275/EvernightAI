import pytest

from EvernightAI.core.domain.context import (
    ContextManager,
    ContextOrganizer,
    ContextRegister,
)
from EvernightAI.core.error.context import ContextNotFoundError
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.tool import ToolDefinition


def make_message(text: str) -> Content:
    return Content(
        role=MessageRole.USER,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def test_context_register_stores_contexts() -> None:
    register = ContextRegister()
    context = Context(context_id="ctx-1", messages=[make_message("Hello")])

    register.register(context)

    assert register.has("ctx-1") is True
    assert register.get("ctx-1") == context
    assert register.list_contexts() == [context]


def test_context_register_raises_for_missing_context() -> None:
    register = ContextRegister()

    with pytest.raises(ContextNotFoundError):
        register.get("missing")

    with pytest.raises(ContextNotFoundError):
        register.unregister("missing")


@pytest.mark.asyncio
async def test_context_manager_creates_and_appends_messages() -> None:
    manager = ContextManager(ContextRegister())
    context = await manager.create(Context(context_id="ctx-1"))

    updated = await manager.append("ctx-1", make_message("Hello"))

    assert context.messages == []
    assert updated.messages == [make_message("Hello")]
    assert await manager.get("ctx-1") == updated


@pytest.mark.asyncio
async def test_context_manager_replaces_and_deletes_contexts() -> None:
    manager = ContextManager(ContextRegister())
    await manager.create(Context(context_id="ctx-1"))

    replacement = Context(
        context_id="ctx-1",
        messages=[make_message("Replacement")],
        metadata={"source": "test"},
    )
    updated = await manager.replace(replacement)

    assert updated == replacement
    assert await manager.list_contexts() == [replacement]

    await manager.delete("ctx-1")

    assert await manager.list_contexts() == []


@pytest.mark.asyncio
async def test_context_manager_rejects_missing_context_updates() -> None:
    manager = ContextManager(ContextRegister())

    with pytest.raises(ContextNotFoundError):
        await manager.append("missing", make_message("Hello"))

    with pytest.raises(ContextNotFoundError):
        await manager.replace(Context(context_id="missing"))


@pytest.mark.asyncio
async def test_context_manager_clears_contexts() -> None:
    manager = ContextManager(ContextRegister())
    await manager.create(Context(context_id="ctx-1"))
    await manager.create(Context(context_id="ctx-2"))

    await manager.clear()

    assert await manager.list_contexts() == []


def test_context_organizer_builds_basic_window() -> None:
    organizer = ContextOrganizer()
    context = Context(
        context_id="ctx-1",
        messages=[make_message("Existing")],
        metadata={"topic": "basic"},
    )

    window = organizer.organize(
        context,
        messages=[make_message("Current")],
    )

    assert window.context_id == "ctx-1"
    assert window.messages == [make_message("Existing"), make_message("Current")]
    assert window.metadata == {"topic": "basic"}
    assert context.messages == [make_message("Existing")]


def test_context_organizer_builds_chat_request() -> None:
    organizer = ContextOrganizer()
    tool = ToolDefinition(
        name="lookup",
        description="Lookup a value",
        parameters_schema={"type": "object"},
    )
    context = Context(
        context_id="ctx-1",
        messages=[make_message("Existing")],
        metadata={"topic": "basic"},
    )

    request = organizer.to_chat_request(
        context,
        model_id="model-1",
        messages=[make_message("Current")],
        tools=[tool],
        metadata={"request_id": "req-1"},
    )

    assert request.model_id == "model-1"
    assert request.messages == [make_message("Existing"), make_message("Current")]
    assert request.tools == [tool]
    assert request.metadata == {
        "topic": "basic",
        "request_id": "req-1",
        "context_id": "ctx-1",
    }
