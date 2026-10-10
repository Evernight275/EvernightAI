from datetime import datetime

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class ApiKeyInfo(EvernightAISchema):
    key_id: str
    owner_id: str
    name: str
    prefix: str
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class IssuedApiKey(EvernightAISchema):
    api_key: str = Field(repr=False)
    key: ApiKeyInfo
