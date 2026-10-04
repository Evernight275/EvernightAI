from typing import Literal

from pydantic import ConfigDict, Field

from EvernightAI.core.schema.base import EvernightAISchema


class ImageToolReference(EvernightAISchema):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(
        min_length=1,
        max_length=256,
        description="Saved image record ID returned by a previous image tool call",
    )
    image_index: int = Field(
        default=0, ge=0, lt=10, description="Zero-based image index in that record"
    )


class ImageToolRequest(EvernightAISchema):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(
        min_length=1,
        max_length=32000,
        description="Describe the image to generate or the changes to reference images",
    )
    provider_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Optional image provider ID; omitted uses a configured image provider",
    )
    model_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Optional image model ID; omitted uses a declared image model, or the reference image's model when editing",
    )
    references: list[ImageToolReference] = Field(
        default_factory=list,
        max_length=16,
        description="Saved images to edit, in prompt order. Omit for text-to-image generation. Never provide Base64 or remote URLs.",
    )
    count: int = Field(default=1, ge=1, le=10, strict=True)
    size: str | None = Field(default=None, min_length=1, max_length=64)
    quality: str | None = Field(
        default="high",
        min_length=1,
        max_length=64,
        description="Requested image quality; defaults to high. Set null to use the provider default.",
    )
    output_format: Literal["png", "jpeg", "webp"] | None = Field(
        default="png",
        description="Requested image format; defaults to lossless PNG. Set null to use the provider default.",
    )
    timeout_seconds: float = Field(
        default=180,
        gt=0,
        le=600,
        description="Image request timeout in seconds, independent of the chat model timeout. Use a longer timeout for slow image models, up to 600 seconds.",
    )
