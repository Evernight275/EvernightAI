from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import ConfigDict, Field

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.image import ImageEditRequest, ImageGenerationRequest


ImageTaskStatus = Literal["queued", "running", "succeeded", "failed", "interrupted"]


class ImageTaskSubmit(EvernightAISchema):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    provider_id: str = Field(min_length=1, max_length=256)
    request: ImageEditRequest | ImageGenerationRequest
    session_id: str | None = Field(default=None, min_length=1, max_length=256)


class ImageTaskSummary(EvernightAISchema):
    task_id: str
    provider_id: str
    model_id: str
    prompt_preview: str
    kind: Literal["generate", "edit"]
    session_id: str | None = None
    status: ImageTaskStatus
    record_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ImageTask(ImageTaskSubmit):
    owner_id: str | None = None
    status: ImageTaskStatus = "queued"
    record_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    worker_id: str | None = None
    lease_expires_at: datetime | None = None

    def summary(self) -> ImageTaskSummary:
        return ImageTaskSummary(
            task_id=self.task_id,
            provider_id=self.provider_id,
            model_id=self.request.model_id,
            prompt_preview=self.request.prompt[:160],
            kind="edit" if isinstance(self.request, ImageEditRequest) else "generate",
            session_id=self.session_id,
            status=self.status,
            record_id=self.record_id,
            error_type=self.error_type,
            error_message=self.error_message,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class ImageTaskPage(EvernightAISchema):
    items: list[ImageTaskSummary]
    next_cursor: str | None = None
