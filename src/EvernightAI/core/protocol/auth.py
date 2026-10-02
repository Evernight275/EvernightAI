from typing import Protocol

from EvernightAI.core.schema.auth import AuthDecision, AuthRequest, Principal


class AuthDeviceProtocol(Protocol):
    def principal(self, credential: object) -> Principal: ...


class AuthPolicyProtocol(Protocol):
    def authorize(self, request: AuthRequest) -> AuthDecision: ...


class AuthorizerProtocol(Protocol):
    def authorize(self, request: AuthRequest) -> AuthDecision: ...

    def require(self, request: AuthRequest) -> None: ...
