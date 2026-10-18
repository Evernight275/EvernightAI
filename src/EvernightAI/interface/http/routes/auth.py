from datetime import datetime
from typing import cast

from fastapi import APIRouter, Request, Response, status
from pydantic import Field

from EvernightAI.core.error.auth import AuthLoginNotConfiguredError
from EvernightAI.core.protocol.api_key import ApiKeyManagerProtocol
from EvernightAI.core.schema.api_key import ApiKeyInfo, IssuedApiKey
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


class AuthOptions(EvernightAISchema):
    authentication_enabled: bool
    login_enabled: bool


class LoginRequest(EvernightAISchema):
    username: str
    password: str


class LoginResponse(EvernightAISchema):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    principal: AuthIdentity


class ApiKeyCreateRequest(EvernightAISchema):
    name: str = Field(min_length=1, max_length=120)
    expires_at: datetime | None = None


@router.get("/config", response_model=AuthOptions)
def auth_options(request: Request, response: Response) -> AuthOptions:
    """Tell a signed-out client how it may sign in. Requires no credential."""
    response.headers["Cache-Control"] = "no-store"
    return AuthOptions(
        authentication_enabled=request.app.state.auth_device is not None,
        login_enabled=_login_device(request) is not None,
    )


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


@router.post("/api-keys", response_model=IssuedApiKey, status_code=201)
def create_api_key(payload: ApiKeyCreateRequest, request: Request) -> IssuedApiKey:
    principal = _require_login_device(request).principal_for_request(request)
    return _require_api_key_manager(request).issue(
        principal.principal_id, payload.name, expires_at=payload.expires_at
    )


@router.get("/api-keys", response_model=list[ApiKeyInfo])
def list_api_keys(request: Request) -> list[ApiKeyInfo]:
    principal = _require_login_device(request).principal_for_request(request)
    return _require_api_key_manager(request).list_keys(principal.principal_id)


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(key_id: str, request: Request) -> Response:
    principal = _require_login_device(request).principal_for_request(request)
    _require_api_key_manager(request).revoke(principal.principal_id, key_id)
    return Response(status_code=204)


def _require_api_key_manager(request: Request) -> ApiKeyManagerProtocol:
    manager = cast(ApiKeyManagerProtocol | None, request.app.state.api_key_manager)
    if manager is None:
        raise AuthLoginNotConfiguredError("API key management is not configured")
    return manager


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
