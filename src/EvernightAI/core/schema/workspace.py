from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class WorkspaceEntry(EvernightAISchema):
    name: str
    path: str
    is_directory: bool


class WorkspaceDirectory(EvernightAISchema):
    root: str
    path: str
    entries: list[WorkspaceEntry] = Field(default_factory=list)
    truncated: bool = False
