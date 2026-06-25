from typing import Any

import jwt
from fastapi import Request
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError, PyJWTError

from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.interface.http.schema import (
    HttpApiKeyCredential,
    HttpOAuthBearerCredential,
    HttpOAuthJwtConfig,
)
from EvernightAI.interface.http.protocol import (
    HttpAuthDeviceProtocol,
    JwkClientProtocol,
)


class CompositeHttpAuthDevice(HttpAuthDeviceProtocol):
    def __init__(self, devices: list[HttpAuthDeviceProtocol]) -> None:
        self._devices = devices

    def principal_for_request(self, request: Request) -> Principal:
        last_error: AuthRequiredError | None = None
        for device in self._devices:
            try:
                return device.principal_for_request(request)
            except AuthRequiredError as error:
                last_error = error

        if last_error is not None:
            raise last_error

        raise AuthRequiredError("Authentication required")

    def principal(self, credential: object) -> Principal:
        last_error: AuthRequiredError | None = None
        for device in self._devices:
            try:
                return device.principal(credential)
            except AuthRequiredError as error:
                last_error = error

        if last_error is not None:
            raise last_error

        raise AuthRequiredError("Authentication required")


class ApiKeyHttpAuthDevice(HttpAuthDeviceProtocol):
    def __init__(
        self,
        credentials: list[HttpApiKeyCredential],
    ) -> None:
        self._principals_by_key = {
            credential.api_key: credential.principal
            for credential in credentials
            if credential.api_key
        }

    def principal_for_request(self, request: Request) -> Principal:
        return self.principal(_api_key_from_request(request))

    def principal(self, credential: object) -> Principal:
        if credential is None:
            raise AuthRequiredError("Authentication required")
        if not isinstance(credential, str) or credential == "":
            raise AuthRequiredError("Invalid API key")

        return self._principal_for_api_key(credential)

    def _principal_for_api_key(self, api_key: str) -> Principal:
        principal = self._principals_by_key.get(api_key)
        if principal is None:
            raise AuthRequiredError("Invalid API key")

        return principal


class OAuthBearerHttpAuthDevice(HttpAuthDeviceProtocol):
    def __init__(
        self,
        credentials: list[HttpOAuthBearerCredential],
    ) -> None:
        self._principals_by_token = {
            credential.access_token: credential.principal
            for credential in credentials
            if credential.access_token
        }

    def principal_for_request(self, request: Request) -> Principal:
        return self.principal(_bearer_token_from_request(request))

    def principal(self, credential: object) -> Principal:
        if credential is None:
            raise AuthRequiredError("Authentication required")
        if not isinstance(credential, str) or credential == "":
            raise AuthRequiredError("Invalid access token")

        return self._principal_for_access_token(credential)

    def _principal_for_access_token(self, access_token: str) -> Principal:
        principal = self._principals_by_token.get(access_token)
        if principal is None:
            raise AuthRequiredError("Invalid access token")

        return principal


class OAuthJwtBearerHttpAuthDevice(HttpAuthDeviceProtocol):
    def __init__(
        self,
        config: HttpOAuthJwtConfig,
        *,
        jwk_client: JwkClientProtocol | None = None,
    ) -> None:
        if not config.algorithms:
            raise ValueError("OAuth JWT algorithms must not be empty")
        self._config = config
        self._jwk_client = jwk_client or PyJWKClient(config.jwks_url)

    def principal_for_request(self, request: Request) -> Principal:
        return self.principal(_bearer_token_from_request(request))

    def principal(self, credential: object) -> Principal:
        if credential is None:
            raise AuthRequiredError("Authentication required")
        if not isinstance(credential, str) or credential == "":
            raise AuthRequiredError("Invalid access token")

        claims = self._verified_claims(credential)
        principal_id = _string_claim(claims, self._config.principal_id_claim)
        if principal_id is None:
            raise AuthRequiredError("Access token is missing principal claim")

        return Principal(
            principal_id=principal_id,
            principal_type=self._config.principal_type,
            roles=_string_claim_values(claims, self._config.roles_claim),
            permissions=self._permissions_for_claims(claims),
            metadata={
                "issuer": claims.get("iss"),
                "audience": claims.get("aud"),
            },
        )

    def _verified_claims(self, access_token: str) -> dict[str, Any]:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(access_token)
            claims = jwt.decode(
                access_token,
                getattr(signing_key, "key"),
                algorithms=self._config.algorithms,
                audience=self._config.audience,
                issuer=self._config.issuer,
                leeway=self._config.leeway_seconds,
                options={
                    "require": [
                        "exp",
                        "iss",
                        "sub",
                        "aud",
                    ]
                },
            )
        except (PyJWKClientError, PyJWTError) as exc:
            raise AuthRequiredError("Invalid access token", cause=exc) from exc

        return claims

    def _permissions_for_claims(self, claims: dict[str, Any]) -> list[str]:
        permissions = list(self._config.default_permissions)
        permissions.extend(_string_claim_values(claims, self._config.permissions_claim))

        for role in _string_claim_values(claims, self._config.roles_claim):
            permissions.extend(self._config.role_permission_map.get(role, []))

        for scope in _string_claim_values(claims, self._config.scope_claim):
            permissions.extend(self._config.scope_permission_map.get(scope, []))

        return _unique_strings(permissions)


def _api_key_from_request(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token

    api_key = request.headers.get("x-evernight-api-key")
    if api_key:
        return api_key

    return None


def _bearer_token_from_request(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization is None:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token

    return None


def _string_claim(claims: dict[str, Any], claim_path: str) -> str | None:
    value = _claim_value(claims, claim_path)
    if isinstance(value, str) and value != "":
        return value

    return None


def _string_claim_values(claims: dict[str, Any], claim_path: str) -> list[str]:
    value = _claim_value(claims, claim_path)
    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]

    return []


def _claim_value(claims: dict[str, Any], claim_path: str) -> object:
    value: object = claims
    for part in claim_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)

    return value


def _unique_strings(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)

    return unique
