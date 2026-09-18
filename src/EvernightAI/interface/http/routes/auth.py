from typing import cast

from fastapi import APIRouter, Request, Response

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.interface.http.protocol import HttpAuthDeviceProtocol


router = APIRouter(prefix="/auth", tags=["Authentication"])


class AuthIdentity(EvernightAISchema):
    principal_id: str
    principal_type: str
    roles: list[str]
    permissions: list[str]


class AuthSession(EvernightAISchema):
    authentication_enabled: bool
    principal: AuthIdentity | None = None


@router.get("/me", response_model=AuthSession)
def current_identity(request: Request, response: Response) -> AuthSession:
    response.headers["Cache-Control"] = "no-store"
    device = cast(HttpAuthDeviceProtocol | None, request.app.state.auth_device)
    if device is None:
        return AuthSession(authentication_enabled=False)
    principal = device.principal_for_request(request)
    return AuthSession(
        authentication_enabled=True,
        principal=AuthIdentity(
            principal_id=principal.principal_id,
            principal_type=principal.principal_type,
            roles=principal.roles,
            permissions=principal.permissions,
        ),
    )
