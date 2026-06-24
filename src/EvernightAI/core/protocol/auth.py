from EvernightAI.core.protocol.base import EvernightAIProtocol
from EvernightAI.core.schema.auth import AuthDecision, AuthRequest, Principal


class AuthDeviceProtocol(EvernightAIProtocol):
    def principal(self, credential: object) -> Principal: ...


class AuthPolicyProtocol(EvernightAIProtocol):
    def authorize(self, request: AuthRequest) -> AuthDecision: ...


class AuthorizerProtocol(EvernightAIProtocol):
    def authorize(self, request: AuthRequest) -> AuthDecision: ...

    def require(self, request: AuthRequest) -> None: ...
