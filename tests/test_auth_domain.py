import pytest

from EvernightAI.core.domain.auth import (
    AllowAllAuthPolicy,
    Authorizer,
    PermissionAuthPolicy,
    permission_key,
)
from EvernightAI.core.error.auth import AuthPermissionDeniedError
from EvernightAI.core.error.base import PermissionDeniedError
from EvernightAI.core.schema.auth import (
    AuthDecisionStatus,
    AuthPermission,
    AuthRequest,
    Principal,
    PrincipalScope,
    PrincipalType,
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


@pytest.mark.parametrize(
    "granted",
    [
        ["providers:create"],
        ["providers:list", "providers:get", "providers:update"],
        ["contexts:delete"],
        ["providers:*"],
        ["*:delete"],
        ["providers"],
        ["delete"],
        ["providers:del"],
        ["providers:delete:provider-1"],
        ["Providers:Delete"],
        [" providers:delete"],
        ["delete:providers"],
        [""],
    ],
)
def test_permission_policy_denies_permission_that_only_resembles_required(
    granted: list[str],
) -> None:
    request = AuthRequest(
        principal=Principal(principal_id="user-1", permissions=granted),
        permission=AuthPermission(resource="providers", action="delete"),
        resource_id="provider-1",
    )

    decision = PermissionAuthPolicy().authorize(request)

    assert decision.status is AuthDecisionStatus.DENIED
    assert decision.allowed is False
    assert decision.reason == "Permission 'providers:delete' is required"


@pytest.mark.parametrize(
    "principal",
    [
        Principal(principal_id="user-1", roles=["admin"]),
        Principal(principal_id="user-1", roles=["*"]),
        Principal(principal_id="*"),
        Principal(principal_id="svc-1", principal_type=PrincipalType.SERVICE),
        Principal(principal_id="user-1", metadata={"permissions": ["*"]}),
    ],
)
def test_permission_policy_grants_nothing_beyond_listed_permissions(
    principal: Principal,
) -> None:
    request = AuthRequest(
        principal=principal,
        permission=AuthPermission(resource="providers", action="delete"),
    )

    assert PermissionAuthPolicy().authorize(request).allowed is False


def test_permission_policy_ignores_request_supplied_grants() -> None:
    request = AuthRequest(
        principal=Principal(principal_id="user-1", permissions=["providers:list"]),
        permission=AuthPermission(
            resource="providers",
            action="delete",
            scope="*",
            metadata={"permissions": ["*"]},
        ),
        resource_id="*",
        metadata={"permissions": ["providers:delete"]},
    )

    assert PermissionAuthPolicy().authorize(request).allowed is False


def test_authorizer_denial_does_not_carry_over_to_other_principals() -> None:
    authorizer = Authorizer(PermissionAuthPolicy())
    permission = AuthPermission(resource="providers", action="delete")
    admin = Principal(principal_id="admin", permissions=["*"])
    user = Principal(principal_id="user-1", permissions=["providers:list"])

    authorizer.require(AuthRequest(principal=admin, permission=permission))

    with pytest.raises(AuthPermissionDeniedError):
        authorizer.require(AuthRequest(principal=user, permission=permission))


def test_authorizer_denied_error_reports_denied_decision() -> None:
    request = AuthRequest(
        principal=Principal(principal_id="user-1", permissions=["providers:list"]),
        permission=AuthPermission(resource="providers", action="delete"),
    )

    with pytest.raises(AuthPermissionDeniedError) as exc_info:
        Authorizer(PermissionAuthPolicy()).require(request)

    assert isinstance(exc_info.value, PermissionDeniedError)
    assert exc_info.value.detail is not None
    assert '"status":"denied"' in exc_info.value.detail


def test_principal_scope_rejects_other_and_unowned_resources() -> None:
    scope = PrincipalScope.for_principal(Principal(principal_id="alice"))

    assert scope.permits("alice") is True
    assert scope.permits("bob") is False
    assert scope.permits(None) is False
    assert scope.permits("") is False
    assert scope.permits("Alice") is False
