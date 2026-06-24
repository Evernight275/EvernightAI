from fastapi import Request

from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.interface.http.protocol import HttpAuthDeviceProtocol


class HttpApiKeyCredential(EvernightAISchema):
    api_key: str
    principal: Principal


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
