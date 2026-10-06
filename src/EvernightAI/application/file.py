from EvernightAI.core.protocol.file import FileInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.file import FileArtifactInfo


class FileApplication(FileInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    def get_file(
        self, artifact_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> FileArtifactInfo:
        return self._runtime.file_artifacts.get(
            artifact_id, principal_scope=principal_scope
        ).info()

    def read_file(
        self, artifact_id: str, *, principal_scope: PrincipalScope | None = None
    ) -> tuple[FileArtifactInfo, bytes]:
        info = self.get_file(artifact_id, principal_scope=principal_scope)
        content = self._runtime.file_artifacts.read(
            artifact_id, principal_scope=principal_scope
        )
        return info, content
