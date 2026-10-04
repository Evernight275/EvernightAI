import logging

from pydantic import ValidationError

from EvernightAI.core.error.image import (
    ImageHistoryInputError,
    ImageRecordNotFoundError,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.image import (
    ImageGenerationRecord,
    ImageEditRequest,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageHistoryCursor,
    ImageHistoryPage,
)


LOGGER = logging.getLogger("EvernightAI.images")


class ImageApplication:
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def generate(
        self,
        provider_id: str,
        request: ImageGenerationRequest,
        *,
        principal_scope: PrincipalScope | None = None,
        record_id: str | None = None,
    ) -> ImageGenerationResponse:
        request = request.model_copy(deep=True)
        response = await self._runtime.providers.generate_images(provider_id, request)
        return await self._persist(
            provider_id, request, response, principal_scope, record_id
        )

    async def edit(
        self,
        provider_id: str,
        request: ImageEditRequest,
        *,
        principal_scope: PrincipalScope | None = None,
        record_id: str | None = None,
    ) -> ImageGenerationResponse:
        request = request.model_copy(deep=True)
        response = await self._runtime.providers.edit_images(provider_id, request)
        return await self._persist(
            provider_id, request, response, principal_scope, record_id
        )

    async def _persist(
        self,
        provider_id: str,
        request: ImageGenerationRequest | ImageEditRequest,
        response: ImageGenerationResponse,
        principal_scope: PrincipalScope | None,
        record_id: str | None = None,
    ) -> ImageGenerationResponse:
        record = ImageGenerationRecord(
            owner_id=principal_scope.owner_id if principal_scope is not None else None,
            provider_id=provider_id,
            request=request.model_copy(deep=True),
            response=response,
        )
        if record_id is not None:
            record = record.model_copy(update={"record_id": record_id})
        response = response.model_copy(
            update={
                "record_id": record.record_id,
                "persistence_warning": "archive_incomplete"
                if any(not image.base64_data for image in response.images)
                else None,
            }
        )
        record = record.model_copy(update={"response": response})
        # Preserve the paid result before slower URL archival.
        if not self._save(record):
            return response.model_copy(
                update={"record_id": None, "persistence_warning": "save_failed"}
            )
        if (
            self._runtime.image_archive is not None
            and response.persistence_warning is not None
        ):
            try:
                response = await self._runtime.image_archive.archive(response)
            except Exception:
                LOGGER.warning("Image archive failed")
            else:
                try:
                    self._runtime.image_records.update(
                        record.model_copy(update={"response": response})
                    )
                except ImageRecordNotFoundError:
                    response = response.model_copy(
                        update={
                            "record_id": None,
                            "persistence_warning": "record_deleted",
                        }
                    )
                except Exception:
                    LOGGER.warning("Image record archive update failed")
                    response = response.model_copy(
                        update={"persistence_warning": "save_failed"}
                    )
        return response

    def _save(self, record: ImageGenerationRecord) -> bool:
        try:
            self._runtime.image_records.save(record)
        except Exception:
            LOGGER.warning("Image record save failed")
            return False
        return True

    def list_records(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> ImageHistoryPage:
        if not 1 <= limit <= 100:
            raise ImageHistoryInputError(
                "Image history limit must be between 1 and 100"
            )
        try:
            position = (
                ImageHistoryCursor.model_validate_json(cursor) if cursor else None
            )
        except ValidationError as exc:
            raise ImageHistoryInputError("Invalid image history cursor") from exc
        records = self._runtime.image_records.list_records(
            limit=limit + 1, cursor=position, principal_scope=principal_scope
        )
        items = records[:limit]
        next_cursor = None
        if len(records) > limit:
            last = items[-1]
            next_cursor = ImageHistoryCursor(
                created_at=last.created_at, record_id=last.record_id
            ).model_dump_json()
        return ImageHistoryPage(items=items, next_cursor=next_cursor)

    def get_record(
        self, record_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageGenerationRecord:
        return self._runtime.image_records.get(
            record_id, principal_scope=principal_scope
        )

    def delete_record(
        self, record_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> None:
        self._runtime.image_records.delete(record_id, principal_scope=principal_scope)
        self._runtime.image_tasks.delete_for_record(record_id)
