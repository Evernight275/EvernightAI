from EvernightAI.core.protocol.base import EvernightAIProtocol
from EvernightAI.core.schema.workspace import WorkspaceDirectory


class WorkspaceDirectoryProtocol(EvernightAIProtocol):
    def browse(self, path: str) -> WorkspaceDirectory: ...

    def create(self, path: str, name: str) -> WorkspaceDirectory: ...
