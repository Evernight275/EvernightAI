from EvernightAI.core.error.image import (
    ImageRecordConflictError,
    ImageRecordNotFoundError,
)
from EvernightAI.core.protocol.image import ImageGenerationStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.image import (
    ImageGenerationRecord,
    ImageGenerationSummary,
    ImageHistoryCursor,
)


class ImageGenerationStore(ImageGenerationStoreProtocol):
    def __init__(self) -> None:
        self._records: dict[str, ImageGenerationRecord] = {}

    def save(self, record: ImageGenerationRecord) -> None:
        previous = self._records.get(record.record_id)
        if previous is not None and previous.owner_id != record.owner_id:
            raise ImageRecordConflictError("Image record ownership cannot change")
        self._records[record.record_id] = record.model_copy(deep=True)

    def update(self, record: ImageGenerationRecord) -> None:
        self.get(
            record.record_id, principal_scope=PrincipalScope(owner_id=record.owner_id)
        )
        self.save(record)

    def get(
        self, record_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> ImageGenerationRecord:
        record = self._records.get(record_id)
        if record is None or (
            principal_scope is not None and not principal_scope.permits(record.owner_id)
        ):
            raise ImageRecordNotFoundError("Image record not found")
        return record.model_copy(deep=True)

    def list_records(
        self,
        *,
        limit: int,
        cursor: ImageHistoryCursor | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[ImageGenerationSummary]:
        records = [
            record
            for record in self._records.values()
            if principal_scope is None or principal_scope.permits(record.owner_id)
        ]
        records.sort(
            key=lambda record: (record.created_at, record.record_id), reverse=True
        )
        if cursor is not None:
            records = [
                record
                for record in records
                if (record.created_at, record.record_id)
                < (cursor.created_at, cursor.record_id)
            ]
        return [record.summary() for record in records[:limit]]

    def delete(
        self, record_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> None:
        self.get(record_id, principal_scope=principal_scope)
        del self._records[record_id]
