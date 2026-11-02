from datetime import datetime

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class ShellSessionState(EvernightAISchema):
    """Shell state carried between otherwise independent shell commands."""

    session_key: str
    owner_id: str | None = None
    # The project root the state belongs to; state for another root is ignored.
    root: str
    # Relative to root, in POSIX form; "." is the root itself.
    cwd: str = "."
    env: dict[str, str] = Field(default_factory=dict)
    # PATH entries present before the session changed PATH.
    base_path: list[str] | None = None
    updated_at: datetime | None = None
