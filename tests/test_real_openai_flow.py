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
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderType,
)
from EvernightAI.infra.bootstrap import create_runtime


RUN_REAL_OPENAI = os.getenv("EVERNIGHTAI_RUN_REAL_OPENAI") == "1"


@pytest.mark.real_openai
@pytest.mark.skipif(
    not RUN_REAL_OPENAI,
    reason="Set EVERNIGHTAI_RUN_REAL_OPENAI=1 to run the real provider flow.",
)
@pytest.mark.asyncio
async def test_real_openai_compatible_chat_flow() -> None:
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
                        Content(
                            role=MessageRole.USER,
                            content=[
                                ContentPart(
                                    type=ContentPartType.TEXT,
                                    text="Reply with exactly: EvernightAI real flow ok",
                                )
                            ],
                        )
                    ],
                ),
            )
        except ProviderUnavailableError as exc:
            pytest.skip(f"Real provider is unavailable: {exc}")
    finally:
        await app.close()

    assert response.model_id
    assert response.message.role is MessageRole.ASSISTANT
    assert response.message.content
    assert any(
        part.type is ContentPartType.TEXT and part.text
        for part in response.message.content
    )
