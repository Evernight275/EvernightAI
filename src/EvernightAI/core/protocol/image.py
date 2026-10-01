from EvernightAI.core.protocol.base import EvernightAIProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.image import (
    ImageGenerationRecord,
    ImageGenerationResponse,
    ImageGenerationSummary,
    ImageHistoryCursor,
)


class ImageGenerationStoreProtocol(EvernightAIProtocol):
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


class ImageArchiveProtocol(EvernightAIProtocol):
    async def archive(
        self, response: ImageGenerationResponse
    ) -> ImageGenerationResponse: ...
