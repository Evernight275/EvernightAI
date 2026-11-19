from typing import Literal

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class AIApprovalConfig(EvernightAISchema):
    enabled: bool = False
    provider_id: str | None = Field(default=None, min_length=1)
    model_id: str | None = Field(default=None, min_length=1)
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)


class AIApprovalReview(EvernightAISchema):
    decision: Literal["approve", "human"]
    risk: Literal["low", "medium", "high", "unknown"]
    reason: str = Field(min_length=1, max_length=2000)
