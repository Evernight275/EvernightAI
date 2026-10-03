import base64
import binascii
from typing import Any, Literal
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ConfigDict, Field, HttpUrl, field_validator, model_validator

from EvernightAI.core.schema.base import EvernightAISchema


class ImageGenerationRequest(EvernightAISchema):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=256)
    prompt: str = Field(min_length=1, max_length=32000)
    count: int = Field(default=1, ge=1, le=10, strict=True)
    size: str | None = Field(default=None, min_length=1, max_length=64)
    quality: str | None = Field(default=None, min_length=1, max_length=64)
    output_format: Literal["png", "jpeg", "webp"] | None = None
    background: Literal["auto", "transparent", "opaque"] | None = None
    result_format: Literal["url", "base64"] | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("model_id", "prompt", "size", "quality")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Value cannot be blank")
        return value


class GeneratedImage(EvernightAISchema):
    url: HttpUrl | None = None
    base64_data: str | None = Field(default=None, min_length=1)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"] | None = None
    revised_prompt: str | None = None

    @model_validator(mode="after")
    def has_image(self) -> "GeneratedImage":
        if self.url is None and self.base64_data is None:
            raise ValueError("Image URL or Base64 data is required")
        if self.base64_data is not None and self.mime_type is None:
            raise ValueError("Base64 images require a MIME type")
        return self


MAX_IMAGE_INPUT_BYTES = 20 * 1024 * 1024
MAX_IMAGE_INPUT_COUNT = 16
MAX_IMAGE_INPUT_TOTAL_BYTES = 50 * 1024 * 1024


class ImageEditInput(EvernightAISchema):
    model_config = ConfigDict(extra="forbid")

    base64_data: str = Field(
        min_length=1, max_length=4 * ((MAX_IMAGE_INPUT_BYTES + 2) // 3), repr=False
    )
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]

    @model_validator(mode="after")
    def valid_bitmap(self) -> "ImageEditInput":
        try:
            data = base64.b64decode(self.base64_data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Original image must contain valid Base64 data") from exc
        if len(data) > MAX_IMAGE_INPUT_BYTES:
            raise ValueError("Original image must not exceed 20 MiB")
        signatures = {
            "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": data.startswith(b"\xff\xd8\xff"),
            "image/webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP",
        }
        if not signatures[self.mime_type]:
            raise ValueError("Original image format does not match its MIME type")
        return self


class ImageEditRequest(ImageGenerationRequest):
    images: list[ImageEditInput] = Field(min_length=1, max_length=MAX_IMAGE_INPUT_COUNT)

    @model_validator(mode="before")
    @classmethod
    def legacy_single_image(cls, value: Any) -> Any:
        if isinstance(value, dict) and "image" in value and "images" not in value:
            value = dict(value)
            value["images"] = [value.pop("image")]
        return value

    @model_validator(mode="after")
    def input_size_limit(self) -> "ImageEditRequest":
        total = sum(len(base64.b64decode(image.base64_data, validate=True)) for image in self.images)
        if total > MAX_IMAGE_INPUT_TOTAL_BYTES:
            raise ValueError("Reference images must not exceed 50 MiB in total")
        return self


class ImageGenerationUsage(EvernightAISchema):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationResponse(EvernightAISchema):
    model_id: str
    images: list[GeneratedImage] = Field(min_length=1)
    created: int | None = None
    usage: ImageGenerationUsage | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    record_id: str | None = None
    persistence_warning: (
        Literal["archive_incomplete", "save_failed", "record_deleted"] | None
    ) = None


class ImageHistoryCursor(EvernightAISchema):
    created_at: datetime
    record_id: str = Field(min_length=1, max_length=64)

    @field_validator("created_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Cursor timestamp requires a timezone")
        return value.astimezone(timezone.utc)


class ImageGenerationSummary(EvernightAISchema):
    record_id: str
    provider_id: str
    model_id: str
    prompt_preview: str
    image_count: int
    created_at: datetime
    archived: bool


class ImageGenerationRecord(EvernightAISchema):
    record_id: str = Field(default_factory=lambda: uuid4().hex)
    owner_id: str | None = None
    provider_id: str
    request: ImageEditRequest | ImageGenerationRequest
    response: ImageGenerationResponse
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Record timestamp requires a timezone")
        return value.astimezone(timezone.utc)

    def summary(self) -> ImageGenerationSummary:
        return ImageGenerationSummary(
            record_id=self.record_id,
            provider_id=self.provider_id,
            model_id=self.request.model_id,
            prompt_preview=self.request.prompt[:160],
            image_count=len(self.response.images),
            created_at=self.created_at,
            archived=all(
                image.base64_data is not None for image in self.response.images
            ),
        )


class ImageHistoryPage(EvernightAISchema):
    items: list[ImageGenerationSummary]
    next_cursor: str | None = None
