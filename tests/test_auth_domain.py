import pytest

from EvernightAI.core.domain.auth import (
    AllowAllAuthPolicy,
    Authorizer,
    PermissionAuthPolicy,
    permission_key,
)
from EvernightAI.core.error.auth import AuthPermissionDeniedError
from EvernightAI.core.schema.auth import (
    AuthDecisionStatus,
    AuthPermission,
    AuthRequest,
    Principal,
)


def test_permission_key_uses_resource_and_action() -> None:
    assert permission_key(AuthPermission(resource="chat", action="create")) == (
        "chat:create"
    )


def test_allow_all_policy_allows_any_request() -> None:
    request = AuthRequest(
        principal=Principal(principal_id="user-1"),
        permission=AuthPermission(resource="providers", action="create"),
    )

    decision = AllowAllAuthPolicy().authorize(request)

    assert decision.status is AuthDecisionStatus.ALLOWED
    assert decision.allowed is True


def test_permission_policy_allows_exact_permission() -> None:
    request = AuthRequest(
        principal=Principal(
            principal_id="user-1",
            permissions=["providers:create"],
        ),
        permission=AuthPermission(resource="providers", action="create"),
    )

    decision = PermissionAuthPolicy().authorize(request)

    assert decision.status is AuthDecisionStatus.ALLOWED


def test_permission_policy_allows_wildcard_permission() -> None:
    request = AuthRequest(
        principal=Principal(principal_id="admin", permissions=["*"]),
        permission=AuthPermission(resource="agent-runs", action="resume"),
    )

    decision = PermissionAuthPolicy().authorize(request)

    assert decision.allowed is True


def test_authorizer_raises_permission_denied_for_denied_request() -> None:
    request = AuthRequest(
        principal=Principal(principal_id="user-1"),
        permission=AuthPermission(resource="providers", action="delete"),
    )

    with pytest.raises(AuthPermissionDeniedError) as exc_info:
        Authorizer(PermissionAuthPolicy()).require(request)

    assert "providers:delete" in str(exc_info.value)
