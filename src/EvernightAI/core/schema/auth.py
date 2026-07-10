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


class PrincipalScope(EvernightAISchema):
    """Ownership scope passed through application and storage boundaries."""

    owner_id: str | None = None

    @classmethod
    def for_principal(cls, principal: Principal) -> "PrincipalScope":
        return cls(owner_id=principal.principal_id)

    def permits(self, owner_id: str | None) -> bool:
        return self.owner_id is None or owner_id == self.owner_id


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
