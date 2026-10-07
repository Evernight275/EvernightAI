from typing import Protocol

from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.file import FileArtifact, FileArtifactInfo


class FileArtifactStoreProtocol(Protocol):
    def save(self, artifact: FileArtifact, content: bytes) -> None: ...

    def get(
        self, artifact_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> FileArtifact: ...

    def read(
        self, artifact_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> bytes: ...


class FileInterfaceProtocol(Protocol):
    def upload_file(
        self, name: str, content: bytes, *, principal_scope: PrincipalScope | None = None
    ) -> FileArtifactInfo: ...

    def get_file(
        self, artifact_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> FileArtifactInfo: ...

    def read_file(
        self, artifact_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> tuple[FileArtifactInfo, bytes]: ...
