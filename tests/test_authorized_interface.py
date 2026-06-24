import pytest

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import (
    AuthorizedEvernightInterface,
    require_permission,
)
from EvernightAI.core.error.auth import AuthPermissionDeniedError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.provider import ProviderConfig, ProviderType


def test_require_permission_uses_resource_action_permission_key() -> None:
    principal = Principal(principal_id="user-1", permissions=["tools:list"])

    require_permission(
        Authorizer(PermissionAuthPolicy()),
        principal,
        "tools",
        "list",
    )


def test_require_permission_rejects_missing_permission() -> None:
    principal = Principal(principal_id="user-1")

    with pytest.raises(AuthPermissionDeniedError) as exc_info:
        require_permission(
            Authorizer(PermissionAuthPolicy()),
            principal,
            "providers",
            "create",
            "provider-1",
        )

    assert "providers:create" in str(exc_info.value)


@pytest.mark.asyncio
async def test_authorized_interface_delegates_when_permission_is_allowed() -> None:
    interface = _authorized_interface(
        permissions=[
            "providers:create",
            "contexts:create",
            "tools:list",
        ]
    )

    provider = await interface.providers.create_provider(
        ProviderConfig(
            provider_id="provider-1",
            name="Fake",
            type=ProviderType.OPENAI,
        )
    )
    context = await interface.chat.create_context(
        Context(context_id="ctx-1", messages=[])
    )
    tools = interface.tools.list_tools()

    assert provider.provider_id == "provider-1"
    assert context.context_id == "ctx-1"
    assert tools == []


@pytest.mark.asyncio
async def test_authorized_interface_stops_denied_call_before_inner_work() -> None:
    runtime = create_runtime()
    interface = AuthorizedEvernightInterface(
        create_interface(runtime),
        Authorizer(PermissionAuthPolicy()),
        Principal(principal_id="user-1"),
    )

    with pytest.raises(AuthPermissionDeniedError):
        await interface.providers.create_provider(
            ProviderConfig(
                provider_id="provider-1",
                name="Fake",
                type=ProviderType.OPENAI,
            )
        )

    assert await runtime.providers.list_instances() == []


def test_authorized_interface_preserves_runtime_and_close_delegation() -> None:
    runtime = create_runtime()
    inner = create_interface(runtime)
    interface = AuthorizedEvernightInterface(
        inner,
        Authorizer(PermissionAuthPolicy()),
        Principal(principal_id="user-1", permissions=["*"]),
    )

    assert interface.runtime is runtime


def _authorized_interface(
    *,
    permissions: list[str],
) -> AuthorizedEvernightInterface:
    return AuthorizedEvernightInterface(
        create_interface(create_runtime()),
        Authorizer(PermissionAuthPolicy()),
        Principal(principal_id="user-1", permissions=permissions),
    )
