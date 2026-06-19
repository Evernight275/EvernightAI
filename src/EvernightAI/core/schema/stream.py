from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class SSEEvent(EvernightAISchema):
    """SSE事件"""

    data: str
    event: str | None = None
    event_id: str | None = Field(default=None, alias="id")
    retry: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
