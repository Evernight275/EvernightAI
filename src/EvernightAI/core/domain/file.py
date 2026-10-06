from threading import RLock

from EvernightAI.core.error.base import ConflictError, NotFoundError, ValidationError
from EvernightAI.core.protocol.file import FileArtifactStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.file import FileArtifact


MAX_FILE_ARTIFACT_BYTES = 20 * 1024 * 1024


def validate_file_content(artifact: FileArtifact, content: bytes) -> None:
    if len(content) != artifact.size_bytes or len(content) > MAX_FILE_ARTIFACT_BYTES:
        raise ValidationError("展示文件大小无效，最多支持 20 MiB")


class FileArtifactStore(FileArtifactStoreProtocol):
    def __init__(self) -> None:
        self._files: dict[str, tuple[FileArtifact, bytes]] = {}
        self._lock = RLock()

    def save(self, artifact: FileArtifact, content: bytes) -> None:
        validate_file_content(artifact, content)
        with self._lock:
            if artifact.artifact_id in self._files:
                raise ConflictError("展示文件已存在")
            self._files[artifact.artifact_id] = (
                artifact.model_copy(deep=True),
                content,
            )

    def _get(
        self, artifact_id: str, scope: PrincipalScope | None
    ) -> tuple[FileArtifact, bytes]:
        result = self._files.get(artifact_id)
        if result is None or (
            scope is not None and not scope.permits(result[0].owner_id)
        ):
            raise NotFoundError("展示文件不存在")
        return result

    def get(
        self, artifact_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> FileArtifact:
        with self._lock:
            return self._get(artifact_id, principal_scope)[0].model_copy(deep=True)

    def read(
        self, artifact_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> bytes:
        with self._lock:
            return self._get(artifact_id, principal_scope)[1]
