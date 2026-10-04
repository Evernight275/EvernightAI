from datetime import datetime, timezone

from EvernightAI.core.error.image import (
    ImageTaskConflictError,
    ImageTaskLimitError,
    ImageTaskNotFoundError,
)
from EvernightAI.core.protocol.image import ImageTaskStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.image import ImageHistoryCursor
from EvernightAI.core.schema.image_task import ImageTask, ImageTaskSummary


MAX_ACTIVE_IMAGE_TASKS = 10


def same_submission(first: ImageTask, second: ImageTask) -> bool:
    return (first.owner_id, first.provider_id, first.request, first.session_id) == (
        second.owner_id,
        second.provider_id,
        second.request,
        second.session_id,
    )


def interrupted(task: ImageTask) -> ImageTask:
    return task.model_copy(
        update={
            "status": "interrupted",
            "updated_at": datetime.now(timezone.utc),
            "error_type": "ImageTaskInterrupted",
            "worker_id": None,
            "lease_expires_at": None,
            "error_message": "服务中断，未自动重新生成。请先检查历史图片，再决定是否提交新任务。",
        }
    )


class ImageTaskStore(ImageTaskStoreProtocol):
    def __init__(self) -> None:
        self._tasks: dict[str, ImageTask] = {}

    def has_active(self) -> bool:
        return any(
            task.status in ("queued", "running") for task in self._tasks.values()
        )

    def delete_for_record(self, record_id: str) -> None:
        self._tasks.pop(record_id, None)

    def create(self, task: ImageTask) -> bool:
        previous = self._tasks.get(task.task_id)
        if previous is not None:
            if previous.owner_id != task.owner_id:
                raise ImageTaskNotFoundError("Image task not found")
            if not same_submission(previous, task):
                raise ImageTaskConflictError(
                    "Image task ID already belongs to another request"
                )
            return False
        count = sum(
            item.owner_id == task.owner_id and item.status in ("queued", "running")
            for item in self._tasks.values()
        )
        if count >= MAX_ACTIVE_IMAGE_TASKS:
            raise ImageTaskLimitError("最多同时保留 10 个待完成的图片任务")
        self._tasks[task.task_id] = task.model_copy(deep=True)
        return True

    def get(
        self, task_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageTask:
        task = self._tasks.get(task_id)
        if task is None or (
            principal_scope is not None and not principal_scope.permits(task.owner_id)
        ):
            raise ImageTaskNotFoundError("Image task not found")
        return task.model_copy(deep=True)

    def get_summary(
        self, task_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageTaskSummary:
        return self.get(task_id, principal_scope=principal_scope).summary()

    def list_tasks(
        self,
        *,
        limit: int,
        cursor: ImageHistoryCursor | None = None,
        session_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[ImageTaskSummary]:
        tasks = [
            task
            for task in self._tasks.values()
            if (principal_scope is None or principal_scope.permits(task.owner_id))
            and (session_id is None or task.session_id == session_id)
            and (
                cursor is None
                or (task.created_at, task.task_id)
                < (cursor.created_at, cursor.record_id)
            )
        ]
        tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
        return [task.summary() for task in tasks[:limit]]

    def claim(self, worker_id: str, lease_expires_at: datetime) -> ImageTask | None:
        tasks = sorted(
            (task for task in self._tasks.values() if task.status == "queued"),
            key=lambda task: (task.created_at, task.task_id),
        )
        if not tasks:
            return None
        task = tasks[0].model_copy(
            update={
                "status": "running",
                "worker_id": worker_id,
                "lease_expires_at": lease_expires_at,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._tasks[task.task_id] = task
        return task.model_copy(deep=True)

    def renew(self, task_id: str, worker_id: str, lease_expires_at: datetime) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status != "running" or task.worker_id != worker_id:
            return False
        self._tasks[task_id] = task.model_copy(
            update={"lease_expires_at": lease_expires_at}
        )
        return True

    def finish(self, task: ImageTask, worker_id: str) -> bool:
        current = self._tasks.get(task.task_id)
        if (
            current is None
            or current.status != "running"
            or current.worker_id != worker_id
        ):
            return False
        self._tasks[task.task_id] = task.model_copy(
            deep=True, update={"worker_id": None, "lease_expires_at": None}
        )
        return True

    def recover_expired(self, now: datetime) -> None:
        for task in list(self._tasks.values()):
            if task.status == "running" and (
                task.lease_expires_at is None or task.lease_expires_at <= now
            ):
                self._tasks[task.task_id] = interrupted(task)
