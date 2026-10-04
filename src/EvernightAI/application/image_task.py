import asyncio
from datetime import datetime, timezone

from pydantic import ValidationError

from EvernightAI.application.image import ImageApplication
from EvernightAI.core.domain.image_task import same_submission
from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.error.image import (
    ImageRecordNotFoundError,
    ImageHistoryInputError,
    ImageTaskConflictError,
    ImageTaskNotFoundError,
)
from EvernightAI.core.error.provider import (
    ProviderCapabilityUnsupportedError,
    ProviderDisabledError,
    ProviderError,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.image import ImageEditRequest, ImageHistoryCursor
from EvernightAI.core.schema.image_task import (
    ImageTask,
    ImageTaskPage,
    ImageTaskSubmit,
    ImageTaskSummary,
)
from EvernightAI.core.schema.provider import ProviderModelCapability


class ImageTaskApplication:
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def submit(
        self,
        submission: ImageTaskSubmit,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> ImageTaskSummary:
        task = ImageTask(
            **submission.model_dump(),
            owner_id=principal_scope.owner_id if principal_scope else None,
        )
        try:
            previous = self._runtime.image_tasks.get(
                task.task_id, principal_scope=principal_scope
            )
        except ImageTaskNotFoundError:
            pass
        else:
            if not same_submission(previous, task):
                raise ImageTaskConflictError(
                    "Image task ID already belongs to another request"
                )
            return self.get(previous.task_id, principal_scope=principal_scope)
        info = await self._runtime.providers.get_info(task.provider_id)
        if not info.is_enabled:
            raise ProviderDisabledError("The image provider is disabled")
        model = next(
            (
                model
                for model in info.model.values()
                if model.model_id == task.request.model_id
            ),
            None,
        )
        if (
            model is not None
            and model.capabilities
            and ProviderModelCapability.IMAGE_GENERATION not in model.capabilities
        ):
            raise ProviderCapabilityUnsupportedError(
                "The model does not support image generation"
            )
        if task.session_id is not None:
            await self._runtime.sessions.get(
                task.session_id, principal_scope=principal_scope
            )
        executor = self._runtime.image_task_executor
        if executor is None:
            raise ConfigurationError("Background image tasks are not configured")
        self._runtime.image_tasks.create(task)
        await executor.start()
        executor.wake()
        return self._runtime.image_tasks.get(
            task.task_id, principal_scope=principal_scope
        ).summary()

    def get(
        self, task_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageTaskSummary:
        summary = self._runtime.image_tasks.get_summary(
            task_id, principal_scope=principal_scope
        )
        return self._recover_result(summary, principal_scope)

    def _recover_result(
        self, summary: ImageTaskSummary, scope: PrincipalScope | None
    ) -> ImageTaskSummary:
        if summary.status not in ("interrupted", "failed"):
            return summary
        try:
            record = self._runtime.image_records.get(
                summary.task_id, principal_scope=scope
            )
        except ImageRecordNotFoundError:
            return summary
        return summary.model_copy(
            update={
                "record_id": record.record_id,
                "error_message": f"{summary.error_message or '任务中断。'} 已返回的图片结果仍可查看。",
            }
        )

    def list(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        session_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> ImageTaskPage:
        if not 1 <= limit <= 100:
            raise ImageHistoryInputError("Image task limit must be between 1 and 100")
        try:
            position = (
                ImageHistoryCursor.model_validate_json(cursor) if cursor else None
            )
        except ValidationError as exc:
            raise ImageHistoryInputError("Invalid image task cursor") from exc
        tasks = self._runtime.image_tasks.list_tasks(
            limit=limit + 1,
            cursor=position,
            session_id=session_id,
            principal_scope=principal_scope,
        )
        items = [self._recover_result(task, principal_scope) for task in tasks[:limit]]
        next_cursor = None
        if len(tasks) > limit:
            last = items[-1]
            next_cursor = ImageHistoryCursor(
                created_at=last.created_at, record_id=last.task_id
            ).model_dump_json()
        return ImageTaskPage(items=items, next_cursor=next_cursor)

    async def execute(self, task: ImageTask) -> ImageTask:
        scope = PrincipalScope(owner_id=task.owner_id)
        app = ImageApplication(self._runtime)
        try:
            async with asyncio.timeout(task.request.timeout_seconds or 600):
                if isinstance(task.request, ImageEditRequest):
                    response = await app.edit(
                        task.provider_id,
                        task.request,
                        principal_scope=scope,
                        record_id=task.task_id,
                    )
                else:
                    response = await app.generate(
                        task.provider_id,
                        task.request,
                        principal_scope=scope,
                        record_id=task.task_id,
                    )
            if not response.record_id:
                return task.model_copy(
                    update={
                        "status": "failed",
                        "updated_at": datetime.now(timezone.utc),
                        "error_type": "ImagePersistenceError",
                        "error_message": "图片结果未能保存或已被删除，请检查历史记录。",
                    }
                )
            return task.model_copy(
                update={
                    "status": "succeeded",
                    "record_id": response.record_id,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
        except ProviderError as exc:
            error_type, message = exc.error_type, str(exc)
        except TimeoutError:
            error_type, message = "ImageTaskTimeout", "图片任务超时，未自动重新生成。"
        except Exception:
            error_type, message = "ImageTaskError", "图片任务执行失败，未自动重新生成。"
        return task.model_copy(
            update={
                "status": "failed",
                "error_type": error_type,
                "error_message": message[:2000],
                "updated_at": datetime.now(timezone.utc),
            }
        )
