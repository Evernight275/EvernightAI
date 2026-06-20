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
from EvernightAI.infra.bootstrap import create_runtime


RUN_REAL_GEMINI = os.getenv("EVERNIGHTAI_RUN_REAL_GEMINI") == "1"


def get_real_gemini_config() -> tuple[str, str, str | None]:
    api_key = os.getenv("EVERNIGHTAI_REAL_GEMINI_API_KEY") or os.getenv(
        "GOOGLE_API_KEY"
    )
    model_id = os.getenv("EVERNIGHTAI_REAL_GEMINI_MODEL")
    base_url = os.getenv("EVERNIGHTAI_REAL_GEMINI_BASE_URL")

    if not api_key:
        pytest.skip(
            "Set EVERNIGHTAI_REAL_GEMINI_API_KEY or GOOGLE_API_KEY to run this test."
        )
    if not model_id:
        pytest.skip("Set EVERNIGHTAI_REAL_GEMINI_MODEL to run this test.")

    return api_key, model_id, base_url


def make_message(text: str) -> Content:
    return Content(
        role=MessageRole.USER,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


@pytest.mark.real_gemini
@pytest.mark.skipif(
    not RUN_REAL_GEMINI,
    reason="Set EVERNIGHTAI_RUN_REAL_GEMINI=1 to run the real Gemini flow.",
)
@pytest.mark.asyncio
async def test_real_gemini_chat_flow() -> None:
    api_key, model_id, base_url = get_real_gemini_config()

    runtime = create_runtime()
    app = ChatApplication(runtime)

    try:
        await app.create_provider(
            ProviderConfig(
                provider_id="real-gemini",
                name="Real Gemini provider",
                type=ProviderType.GOOGLE,
                api_key=api_key,
                base_url=base_url,
            )
        )

        try:
            response = await app.chat(
                "real-gemini",
                ChatRequest(
                    model_id=model_id,
                    messages=[
                        make_message("Reply with exactly: EvernightAI Gemini flow ok")
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
