import os

import pytest

from EvernightAI.application.agent import AgentApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.core.error.provider import ProviderUnavailableError
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentStepType,
    AgentStopReason,
)
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderType,
)
from EvernightAI.bootstrap.runtime import create_runtime


RUN_REAL_OPENAI = os.getenv("EVERNIGHTAI_RUN_REAL_OPENAI") == "1"


def get_real_openai_config() -> tuple[str, str, str | None]:
    api_key = os.getenv("EVERNIGHTAI_REAL_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    model_id = os.getenv("EVERNIGHTAI_REAL_OPENAI_MODEL")
    base_url = os.getenv("EVERNIGHTAI_REAL_OPENAI_BASE_URL") or os.getenv(
        "OPENAI_BASE_URL"
    )

    if not api_key:
        pytest.skip(
            "Set EVERNIGHTAI_REAL_OPENAI_API_KEY or OPENAI_API_KEY to run this test."
        )
    if not model_id:
        pytest.skip("Set EVERNIGHTAI_REAL_OPENAI_MODEL to run this test.")

    return api_key, model_id, base_url


def make_message(text: str, *, role: MessageRole = MessageRole.USER) -> Content:
    return Content(
        role=role,
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=text,
            )
        ],
    )


@pytest.mark.real_openai
@pytest.mark.skipif(
    not RUN_REAL_OPENAI,
    reason="Set EVERNIGHTAI_RUN_REAL_OPENAI=1 to run the real provider flow.",
)
@pytest.mark.asyncio
async def test_real_openai_compatible_chat_flow() -> None:
    api_key, model_id, base_url = get_real_openai_config()

    runtime = create_runtime()
    app = ChatApplication(runtime)

    try:
        await app.create_provider(
            ProviderConfig(
                provider_id="real-openai",
                name="Real OpenAI-compatible provider",
                type=ProviderType.OPENAI,
                api_key=api_key,
                base_url=base_url,
            )
        )

        try:
            response = await app.chat(
                "real-openai",
                ChatRequest(
                    model_id=model_id,
                    messages=[
                        make_message("Reply with exactly: EvernightAI real flow ok")
                    ],
                ),
            )
        except ProviderUnavailableError as exc:
            pytest.skip(f"Real provider is unavailable: {exc}")
    finally:
        await runtime.close()

    assert response.model_id
    assert response.message.role is MessageRole.ASSISTANT
    assert response.message.content
    assert any(
        part.type is ContentPartType.TEXT and part.text
        for part in response.message.content
    )


@pytest.mark.real_openai
@pytest.mark.skipif(
    not RUN_REAL_OPENAI,
    reason="Set EVERNIGHTAI_RUN_REAL_OPENAI=1 to run the real provider flow.",
)
@pytest.mark.asyncio
async def test_real_openai_compatible_agent_flow() -> None:
    api_key, model_id, base_url = get_real_openai_config()

    runtime = create_runtime()
    app = AgentApplication(runtime)

    try:
        await runtime.providers.create(
            ProviderConfig(
                provider_id="real-openai-agent",
                name="Real OpenAI-compatible provider",
                type=ProviderType.OPENAI,
                api_key=api_key,
                base_url=base_url,
            )
        )
        await runtime.contexts.create(Context(context_id="real-agent-context"))

        try:
            result = await app.run_agent(
                AgentRunRequest(
                    provider_id="real-openai-agent",
                    context_id="real-agent-context",
                    model_id=model_id,
                    messages=[
                        make_message(
                            "Reply with exactly: EvernightAI real agent flow ok"
                        )
                    ],
                    max_tool_rounds=0,
                    write_memory=True,
                    metadata={"test": "real_openai_agent_flow"},
                )
            )
        except ProviderUnavailableError as exc:
            pytest.skip(f"Real provider is unavailable: {exc}")
        context = await runtime.contexts.get("real-agent-context")
        memories = await runtime.memories.list_memories()
    finally:
        await runtime.close()

    assert result.stop_reason is AgentStopReason.FINISHED
    assert result.response.model_id
    assert result.response.message.role is MessageRole.ASSISTANT
    assert result.response.message.content
    assert [step.step_type for step in result.steps] == [
        AgentStepType.START,
        AgentStepType.CHAT,
        AgentStepType.STOP,
        AgentStepType.MEMORY_WRITE,
    ]
    assert [message.role for message in context.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert len(memories) == 1
    assert memories[0].scope_id == "real-agent-context"
    assert "EvernightAI real agent flow ok" in memories[0].content
