from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class PrincipalType(StrEnum):
    USER = "user"
    SERVICE = "service"
    ANONYMOUS = "anonymous"


class AuthDecisionStatus(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


class Principal(EvernightAISchema):
    principal_id: str
    principal_type: PrincipalType = PrincipalType.USER
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuthPermission(EvernightAISchema):
    action: str
    resource: str = "*"
    scope: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuthRequest(EvernightAISchema):
    principal: Principal
    permission: AuthPermission
    resource_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuthDecision(EvernightAISchema):
    status: AuthDecisionStatus
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.status is AuthDecisionStatus.ALLOWED
