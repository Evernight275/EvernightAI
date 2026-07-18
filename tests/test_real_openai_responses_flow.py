import os

import pytest

from EvernightAI.application.chat import ChatApplication
from EvernightAI.core.error.provider import ProviderUnavailableError
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.provider import ProviderConfig, ProviderType
from EvernightAI.bootstrap.runtime import create_runtime


RUN_REAL_OPENAI_RESPONSES = os.getenv("EVERNIGHTAI_RUN_REAL_OPENAI_RESPONSES") == "1"


def get_real_openai_responses_config() -> tuple[str, str, str | None]:
    api_key = os.getenv("EVERNIGHTAI_REAL_OPENAI_RESPONSES_API_KEY") or os.getenv(
        "OPENAI_API_KEY"
    )
    model_id = os.getenv("EVERNIGHTAI_REAL_OPENAI_RESPONSES_MODEL")
    base_url = os.getenv("EVERNIGHTAI_REAL_OPENAI_RESPONSES_BASE_URL") or os.getenv(
        "OPENAI_BASE_URL"
    )

    if not api_key:
        pytest.skip(
            "Set EVERNIGHTAI_REAL_OPENAI_RESPONSES_API_KEY or OPENAI_API_KEY to run this test."
        )
    if not model_id:
        pytest.skip("Set EVERNIGHTAI_REAL_OPENAI_RESPONSES_MODEL to run this test.")

    return api_key, model_id, base_url


def make_message(text: str) -> Content:
    return Content(
        role=MessageRole.USER,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


@pytest.mark.real_openai_responses
@pytest.mark.skipif(
    not RUN_REAL_OPENAI_RESPONSES,
    reason=(
        "Set EVERNIGHTAI_RUN_REAL_OPENAI_RESPONSES=1 to run the real OpenAI "
        "Responses flow."
    ),
)
@pytest.mark.asyncio
async def test_real_openai_responses_chat_flow() -> None:
    api_key, model_id, base_url = get_real_openai_responses_config()

    runtime = create_runtime()
    app = ChatApplication(runtime)

    try:
        await runtime.providers.create(
            ProviderConfig(
                provider_id="real-openai-responses",
                name="Real OpenAI Responses provider",
                type=ProviderType.OPENAI_RESPONSES,
                api_key=api_key,
                base_url=base_url,
            )
        )

        try:
            response = await app.chat(
                "real-openai-responses",
                ChatRequest(
                    model_id=model_id,
                    messages=[
                        make_message(
                            "Reply with exactly: EvernightAI Responses flow ok"
                        )
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
