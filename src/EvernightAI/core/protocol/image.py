from datetime import datetime
from typing import Protocol

from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.image import (
    ImageGenerationRecord,
    ImageGenerationResponse,
    ImageGenerationSummary,
    ImageHistoryCursor,
)
from EvernightAI.core.schema.image_task import ImageTask, ImageTaskSummary


class ImageGenerationStoreProtocol(Protocol):
    def save(self, record: ImageGenerationRecord) -> None: ...

    def update(self, record: ImageGenerationRecord) -> None: ...

    def get(
        self, record_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageGenerationRecord: ...

    def list_records(
        self,
        *,
        limit: int,
        cursor: ImageHistoryCursor | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[ImageGenerationSummary]: ...

    def delete(
        self, record_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> None: ...


class ImageArchiveProtocol(Protocol):
    async def archive(
        self, response: ImageGenerationResponse
    ) -> ImageGenerationResponse: ...


class ImageTaskStoreProtocol(Protocol):
    def has_active(self) -> bool: ...

    def create(self, task: ImageTask) -> bool: ...

    def delete_for_record(self, record_id: str) -> None: ...

    def get(
        self, task_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageTask: ...

    def get_summary(
        self, task_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageTaskSummary: ...

    def list_tasks(
        self,
        *,
        limit: int,
        cursor: ImageHistoryCursor | None = None,
        session_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[ImageTaskSummary]: ...

    def claim(self, worker_id: str, lease_expires_at: datetime) -> ImageTask | None: ...

    def renew(
        self, task_id: str, worker_id: str, lease_expires_at: datetime
    ) -> bool: ...

    def finish(self, task: ImageTask, worker_id: str) -> bool: ...

    def recover_expired(self, now: datetime) -> None: ...


class ImageTaskExecutorProtocol(Protocol):
    async def start(self) -> None: ...

    def wake(self) -> None: ...

    async def close(self) -> None: ...
