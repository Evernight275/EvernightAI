from datetime import datetime
from typing import cast

from fastapi import APIRouter, Request, Response, status

from EvernightAI.core.error.auth import AuthLoginNotConfiguredError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.interface.http.protocol import (
    HttpAuthDeviceProtocol,
    HttpLoginDeviceProtocol,
)


router = APIRouter(prefix="/auth", tags=["Authentication"])


class AuthIdentity(EvernightAISchema):
    principal_id: str
    principal_type: str
    roles: list[str]
    permissions: list[str]


class AuthSession(EvernightAISchema):
    authentication_enabled: bool
    login_enabled: bool = False
    principal: AuthIdentity | None = None


class LoginRequest(EvernightAISchema):
    username: str
    password: str


class LoginResponse(EvernightAISchema):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    principal: AuthIdentity


@router.get("/me", response_model=AuthSession)
def current_identity(request: Request, response: Response) -> AuthSession:
    response.headers["Cache-Control"] = "no-store"
    device = cast(HttpAuthDeviceProtocol | None, request.app.state.auth_device)
    if device is None:
        return AuthSession(authentication_enabled=False)
    principal = device.principal_for_request(request)
    return AuthSession(
        authentication_enabled=True,
        login_enabled=_login_device(request) is not None,
        principal=_identity(principal),
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> LoginResponse:
    response.headers["Cache-Control"] = "no-store"
    session = _require_login_device(request).login(payload.username, payload.password)
    return LoginResponse(
        access_token=session.access_token,
        expires_at=session.expires_at,
        principal=_identity(session.principal),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    _require_login_device(request).logout_for_request(request)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "no-store"},
    )


def _login_device(request: Request) -> HttpLoginDeviceProtocol | None:
    return cast(
        HttpLoginDeviceProtocol | None,
        getattr(request.app.state, "login_device", None),
    )


def _require_login_device(request: Request) -> HttpLoginDeviceProtocol:
    device = _login_device(request)
    if device is None:
        raise AuthLoginNotConfiguredError("Password login is not configured")
    return device


def _identity(principal: Principal) -> AuthIdentity:
    return AuthIdentity(
        principal_id=principal.principal_id,
        principal_type=principal.principal_type,
        roles=principal.roles,
        permissions=principal.permissions,
    )
