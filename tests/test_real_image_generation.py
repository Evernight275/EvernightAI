import os

import pytest

from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.error.provider import (
    ProviderRequestTimeoutError,
    ProviderUnavailableError,
)
from EvernightAI.core.schema.image import ImageGenerationRequest
from EvernightAI.core.schema.provider import ProviderConfig, ProviderType


@pytest.mark.real_images
@pytest.mark.skipif(
    os.getenv("EVERNIGHTAI_RUN_REAL_IMAGES") != "1",
    reason="Set EVERNIGHTAI_RUN_REAL_IMAGES=1 to run the paid image generation smoke test.",
)
@pytest.mark.asyncio
async def test_real_openai_compatible_image_generation() -> None:
    api_key = os.getenv("EVERNIGHTAI_REAL_IMAGES_API_KEY") or os.getenv(
        "OPENAI_API_KEY"
    )
    model = os.getenv("EVERNIGHTAI_REAL_IMAGES_MODEL")
    if not api_key or not model:
        pytest.skip(
            "Set EVERNIGHTAI_REAL_IMAGES_API_KEY and EVERNIGHTAI_REAL_IMAGES_MODEL."
        )
    runtime = create_runtime()
    try:
        await runtime.providers.create(
            ProviderConfig(
                provider_id="real-images",
                name="Real Images",
                type=ProviderType.OPENAI,
                api_key=api_key,
                base_url=os.getenv("EVERNIGHTAI_REAL_IMAGES_BASE_URL")
                or os.getenv("OPENAI_BASE_URL"),
            )
        )
        try:
            response = await runtime.providers.generate_images(
                "real-images",
                ImageGenerationRequest(
                    model_id=model,
                    prompt="A single green leaf on a white background.",
                    count=1,
                ),
            )
        except (ProviderUnavailableError, ProviderRequestTimeoutError) as exc:
            pytest.skip(f"Real image provider is unavailable: {exc}")
        assert response.images
        assert all(image.url or image.base64_data for image in response.images)
    finally:
        await runtime.close()
