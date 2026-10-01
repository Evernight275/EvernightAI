import base64
import binascii
from typing import Any, Literal

from openai.types.images_response import ImagesResponse
from pydantic import HttpUrl

from EvernightAI.core.error.provider import ProviderRequestError, ProviderResponseError
from EvernightAI.core.schema.image import (
    GeneratedImage,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageGenerationUsage,
)
from EvernightAI.infra.adapters.provider_usage import token_count
from EvernightAI.infra.adapters.images.bitmap import bitmap_mime


def image_generation_params(request: ImageGenerationRequest) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": request.model_id,
        "prompt": request.prompt,
        "n": request.count,
    }
    for name in ("size", "quality", "output_format", "background"):
        value = getattr(request, name)
        if value is not None:
            params[name] = value
    if request.result_format is not None:
        if request.model_id.startswith("gpt-image-"):
            if request.result_format == "url":
                raise ProviderRequestError(
                    "GPT image models return Base64 images and do not support URL output"
                )
        else:
            params["response_format"] = (
                "b64_json" if request.result_format == "base64" else "url"
            )
    return params


def from_openai_images(
    response: ImagesResponse, request: ImageGenerationRequest
) -> ImageGenerationResponse:
    if not response.data:
        raise ProviderResponseError("The image provider returned no images")
    try:
        images = [
            GeneratedImage(
                url=HttpUrl(item.url) if item.url else None,
                base64_data=item.b64_json,
                mime_type=_image_mime(item.b64_json) if item.b64_json else None,
                revised_prompt=item.revised_prompt,
            )
            for item in response.data
        ]
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProviderResponseError(
            "The image provider returned invalid image data", cause=exc
        ) from exc
    raw_response = response.model_dump(mode="json", warnings=False)
    usage = None
    raw_usage = raw_response.get("usage")
    if raw_usage is not None:
        counts = raw_usage if isinstance(raw_usage, dict) else {}
        usage = ImageGenerationUsage(
            input_tokens=token_count(counts.get("input_tokens")),
            output_tokens=token_count(counts.get("output_tokens")),
            total_tokens=token_count(counts.get("total_tokens")),
            metadata={"provider_usage": raw_usage},
        )
    return ImageGenerationResponse(
        model_id=request.model_id,
        images=images,
        created=token_count(raw_response.get("created")),
        usage=usage,
        metadata={
            key: value
            for key, value in raw_response.items()
            if key not in {"data", "usage", "created"} and value is not None
        },
    )


def _image_mime(value: str) -> Literal["image/png", "image/jpeg", "image/webp"]:
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid Base64 image") from exc
    return bitmap_mime(data)
