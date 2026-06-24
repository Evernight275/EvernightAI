from EvernightAI.core.error.auth import AuthPermissionDeniedError
from EvernightAI.core.protocol.auth import AuthPolicyProtocol, AuthorizerProtocol
from EvernightAI.core.schema.auth import (
    AuthDecision,
    AuthDecisionStatus,
    AuthPermission,
    AuthRequest,
)


class AllowAllAuthPolicy(AuthPolicyProtocol):
    def authorize(self, request: AuthRequest) -> AuthDecision:
        return AuthDecision(status=AuthDecisionStatus.ALLOWED)


class PermissionAuthPolicy(AuthPolicyProtocol):
    def authorize(self, request: AuthRequest) -> AuthDecision:
        required = permission_key(request.permission)
        allowed = set(request.principal.permissions)
        if "*" in allowed or required in allowed:
            return AuthDecision(status=AuthDecisionStatus.ALLOWED)

        return AuthDecision(
            status=AuthDecisionStatus.DENIED,
            reason=f"Permission '{required}' is required",
        )


class Authorizer(AuthorizerProtocol):
    def __init__(self, policy: AuthPolicyProtocol) -> None:
        self._policy = policy

    def authorize(self, request: AuthRequest) -> AuthDecision:
        return self._policy.authorize(request)

    def require(self, request: AuthRequest) -> None:
        decision = self.authorize(request)
        if decision.allowed:
            return

        raise AuthPermissionDeniedError(
            decision.reason or "Permission denied",
            detail=decision.model_dump_json(exclude_none=True),
        )


def permission_key(permission: AuthPermission) -> str:
    return f"{permission.resource}:{permission.action}"
