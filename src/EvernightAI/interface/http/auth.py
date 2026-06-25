from fastapi import Request

from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.interface.http.protocol import HttpAuthDeviceProtocol


class HttpApiKeyCredential(EvernightAISchema):
    api_key: str
    principal: Principal


class HttpOAuthBearerCredential(EvernightAISchema):
    access_token: str
    principal: Principal


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
