from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import ConfigDict, Field

from EvernightAI.core.schema.base import EvernightAISchema


class DisplayFileRequest(EvernightAISchema):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        min_length=1,
        description="File path inside the current working directory. Prefer a relative path, such as plots/chart.png. /workspace/ paths from sandbox tools are also accepted.",
    )
    title: str | None = Field(default=None, max_length=160)
    filename: str | None = Field(default=None, min_length=1, max_length=200)


class FileArtifactInfo(EvernightAISchema):
    artifact_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    title: str | None = None
    mime_type: str
    size_bytes: int = Field(ge=0)
    preview_kind: Literal["image", "html", "none"] = "none"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FileArtifact(FileArtifactInfo):
    owner_id: str | None = None

    def info(self) -> FileArtifactInfo:
        return FileArtifactInfo.model_validate(self.model_dump())
