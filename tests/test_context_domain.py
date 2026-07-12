import pytest

from EvernightAI.core.domain.context import (
    BasicContextStrategy,
    ContextManager,
    ContextOrganizer,
    ContextRegister,
    SummarizingContextStrategy,
    TokenBudgetContextStrategy,
    WindowTrimmingContextStrategy,
)
from EvernightAI.core.error.context import ContextNotFoundError
from EvernightAI.core.protocol.context import (
    ContextSummarizerProtocol,
    ContextTokenEstimatorProtocol,
)
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageStatus,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import (
    MemoryItem,
    MemoryKind,
    MemorySelection,
)
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition


def make_message(text: str) -> Content:
    return Content(
        role=MessageRole.USER,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def make_system_message(text: str) -> Content:
    return Content(
        role=MessageRole.SYSTEM,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def make_assistant_tool_call(tool_call_id: str = "tool-call-1") -> Content:
    return Content(
        role=MessageRole.ASSISTANT,
        tool_calls=[
            ToolCall(
                tool_call_id=tool_call_id,
                tool_call={"name": "lookup", "arguments": {}},
            )
        ],
    )


def make_tool_message(tool_call_id: str = "tool-call-1") -> Content:
    return Content(
        role=MessageRole.TOOL,
        tool_call_id=tool_call_id,
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text='{"ok": true}',
            )
        ],
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


def test_context_organizer_filters_inactive_messages() -> None:
    organizer = ContextOrganizer()
    context = Context(
        context_id="ctx-1",
        messages=[
            make_message("Existing"),
            make_message("Rejected").model_copy(
                update={"status": MessageStatus.REJECTED}
            ),
            make_message("Errored").model_copy(update={"status": MessageStatus.ERROR}),
        ],
    )

    window = organizer.organize(
        context,
        messages=[
            make_message("Current"),
            make_message("Rejected current").model_copy(
                update={"status": MessageStatus.REJECTED}
            ),
        ],
    )

    assert [message.content[0].text for message in window.messages if message.content] == [
        "Existing",
        "Current",
    ]


def test_context_organizer_filters_orphan_tool_call_messages() -> None:
    organizer = ContextOrganizer()
    complete_tool_call = make_assistant_tool_call("complete-call")
    complete_tool_result = make_tool_message("complete-call")
    orphan_tool_call = make_assistant_tool_call("orphan-call")
    orphan_tool_result = make_tool_message("orphan-call")
    context = Context(
        context_id="ctx-1",
        messages=[
            make_message("Existing"),
            complete_tool_call,
            complete_tool_result,
            make_message("After complete"),
            orphan_tool_result,
            orphan_tool_call,
        ],
    )

    window = organizer.organize(context, messages=[make_message("Current")])

    assert window.messages == [
        make_message("Existing"),
        complete_tool_call,
        complete_tool_result,
        make_message("After complete"),
        make_message("Current"),
    ]


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


def test_basic_context_strategy_composes_memory_into_chat_request() -> None:
    strategy = BasicContextStrategy(ContextOrganizer())
    context = Context(
        context_id="ctx-1",
        messages=[make_system_message("System"), make_message("Existing")],
        metadata={"topic": "strategy"},
    )
    memory = MemoryItem(
        memory_id="mem-1",
        content="Prefer concise answers",
        kind=MemoryKind.PREFERENCE,
    )

    request = strategy.compose_chat_request(
        context,
        model_id="model-1",
        messages=[make_message("Current")],
        memory_selection=MemorySelection(
            memories=[memory],
            metadata={"strategy": "test"},
        ),
        metadata={"request_id": "req-1"},
    )

    assert request.model_id == "model-1"
    assert [message.content[0].text for message in request.messages if message.content] == [
        "System",
        "Relevant memory:\n- preference: Prefer concise answers",
        "Existing",
        "Current",
    ]
    assert request.messages[1].metadata == {
        "source": "memory",
        "memory_ids": ["mem-1"],
    }
    assert request.metadata == {
        "topic": "strategy",
        "request_id": "req-1",
        "memory_ids": ["mem-1"],
        "memory_selection": {"strategy": "test"},
        "context_id": "ctx-1",
    }


def test_window_trimming_strategy_is_independent_from_basic_organizer() -> None:
    strategy = WindowTrimmingContextStrategy(
        BasicContextStrategy(ContextOrganizer()),
        max_messages=2,
    )
    context = Context(
        context_id="ctx-1",
        messages=[make_message("one"), make_message("two")],
    )

    request = strategy.compose_chat_request(
        context,
        model_id="model-1",
        messages=[make_message("three")],
    )

    assert request.messages == [make_message("two"), make_message("three")]
    assert request.metadata["context_strategy"]["name"] == "WindowTrimmingContextStrategy"
    assert request.metadata["context_strategy"]["original_message_count"] == 3
    assert request.metadata["context_strategy"]["dropped_message_count"] == 1
    assert request.metadata["context_strategy_steps"] == [
        request.metadata["context_strategy"]
    ]


def test_token_budget_strategy_keeps_newest_messages_within_budget() -> None:
    strategy = TokenBudgetContextStrategy(
        BasicContextStrategy(ContextOrganizer()),
        max_tokens=2,
        estimator=_OneTokenEstimator(),
    )
    context = Context(
        context_id="ctx-1",
        messages=[make_message("one"), make_message("two")],
    )

    request = strategy.compose_chat_request(
        context,
        model_id="model-1",
        messages=[make_message("three")],
    )

    assert request.messages == [make_message("two"), make_message("three")]
    assert request.metadata["context_strategy"]["estimated_tokens"] == 2


def test_window_trimming_keeps_tool_protocol_groups_intact() -> None:
    tool_call = make_assistant_tool_call()
    tool_result = make_tool_message()
    strategy = WindowTrimmingContextStrategy(
        BasicContextStrategy(ContextOrganizer()),
        max_messages=2,
    )

    request = strategy.compose_chat_request(
        Context(
            context_id="ctx-1",
            messages=[make_message("old"), tool_call, tool_result],
        ),
        model_id="model-1",
    )

    assert request.messages == [tool_call, tool_result]


def test_token_budget_keeps_tool_protocol_groups_intact() -> None:
    tool_call = make_assistant_tool_call()
    tool_result = make_tool_message()
    strategy = TokenBudgetContextStrategy(
        BasicContextStrategy(ContextOrganizer()),
        max_tokens=1,
        estimator=_OneTokenEstimator(),
    )

    request = strategy.compose_chat_request(
        Context(context_id="ctx-1", messages=[tool_call, tool_result]),
        model_id="model-1",
    )

    assert request.messages == [tool_call, tool_result]


def test_summarizing_strategy_uses_injected_summarizer() -> None:
    summarizer = _RecordingSummarizer()
    strategy = SummarizingContextStrategy(
        BasicContextStrategy(ContextOrganizer()),
        summarizer,
        summarize_after_messages=2,
        keep_recent_messages=1,
    )
    context = Context(
        context_id="ctx-1",
        messages=[make_message("one"), make_message("two")],
    )

    request = strategy.compose_chat_request(
        context,
        model_id="model-1",
        messages=[make_message("three")],
    )

    assert summarizer.messages == [[make_message("one"), make_message("two")]]
    assert request.messages == [
        Content(
            role=MessageRole.SYSTEM,
            content=[ContentPart(type=ContentPartType.TEXT, text="summary")],
        ),
        make_message("three"),
    ]
    assert request.metadata["context_strategy"] == {
        "name": "SummarizingContextStrategy",
        "summarized_message_count": 2,
    }


def test_summarizing_strategy_keeps_recent_tool_group_intact() -> None:
    tool_call = make_assistant_tool_call()
    tool_result = make_tool_message()
    summarizer = _RecordingSummarizer()
    strategy = SummarizingContextStrategy(
        BasicContextStrategy(ContextOrganizer()),
        summarizer,
        summarize_after_messages=2,
        keep_recent_messages=1,
    )

    request = strategy.compose_chat_request(
        Context(
            context_id="ctx-1",
            messages=[make_message("old"), tool_call, tool_result],
        ),
        model_id="model-1",
    )

    assert summarizer.messages == [[make_message("old")]]
    assert request.messages[1:] == [tool_call, tool_result]


def test_window_trimming_keeps_current_messages_even_when_over_limit() -> None:
    current = make_message("current")
    strategy = WindowTrimmingContextStrategy(
        BasicContextStrategy(ContextOrganizer()),
        max_messages=1,
    )

    request = strategy.compose_chat_request(
        Context(
            context_id="ctx-1",
            messages=[make_system_message("system"), make_message("old")],
        ),
        model_id="model-1",
        messages=[current],
    )

    assert request.messages == [make_system_message("system"), current]
    assert request.metadata["context_strategy"]["degraded"] is True
    assert request.metadata["context_strategy"]["degradation_reasons"] == [
        "protected_messages_exceed_max_messages",
        "max_messages_dropped_messages",
    ]


def test_token_budget_keeps_current_tool_group_even_when_over_budget() -> None:
    tool_call = make_assistant_tool_call()
    tool_result = make_tool_message()
    strategy = TokenBudgetContextStrategy(
        BasicContextStrategy(ContextOrganizer()),
        max_tokens=1,
        estimator=_OneTokenEstimator(),
    )

    request = strategy.compose_chat_request(
        Context(context_id="ctx-1", messages=[make_message("old")]),
        model_id="model-1",
        messages=[tool_call, tool_result],
    )

    assert request.messages == [tool_call, tool_result]
    assert request.metadata["context_strategy"]["estimated_tokens"] == 2
    assert request.metadata["context_strategy"]["degraded"] is True
    assert request.metadata["context_strategy"]["degradation_reasons"] == [
        "protected_messages_exceed_token_budget",
        "token_budget_dropped_messages",
    ]


class _OneTokenEstimator(ContextTokenEstimatorProtocol):
    def estimate(self, message: Content) -> int:
        return 1


class _RecordingSummarizer(ContextSummarizerProtocol):
    def __init__(self) -> None:
        self.messages: list[list[Content]] = []

    def summarize(self, messages: list[Content]) -> Content:
        self.messages.append(messages)
        return Content(
            role=MessageRole.SYSTEM,
            content=[ContentPart(type=ContentPartType.TEXT, text="summary")],
        )
