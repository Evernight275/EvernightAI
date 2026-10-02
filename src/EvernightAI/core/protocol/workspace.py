from typing import Protocol

from EvernightAI.core.schema.workspace import WorkspaceDirectory


class WorkspaceDirectoryProtocol(Protocol):
    def browse(self, path: str) -> WorkspaceDirectory: ...

    def create(self, path: str, name: str) -> WorkspaceDirectory: ...
