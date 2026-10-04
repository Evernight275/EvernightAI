from pathlib import Path

import httpx
import pytest

from EvernightAI.application.agent import AgentRunApplication
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.tool import (
    BasicToolSafetyPolicy,
    ToolManager,
    ToolRegister,
)
from EvernightAI.core.domain.tool_policy import ToolPolicyStore
from EvernightAI.core.error.tool import ToolPolicyError
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunStatus
from EvernightAI.core.schema.auth import Principal, PrincipalScope
from EvernightAI.core.schema.tool import (
    ToolAccessMode,
    ToolApprovalDecision,
    ToolApprovalStatus,
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolSafetyDecision,
    ToolSafetyLevel,
)
from EvernightAI.infra.adapters.tool.sqlite import SQLiteToolPolicyStore
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import ApiKeyHttpAuthDevice
from EvernightAI.interface.http.schema import HttpApiKeyCredential
from tests.test_image_tool import ChatImageProvider, configure, message


def test_empty_permission_sets_clear_defaults():
    policy = BasicToolSafetyPolicy(
        blocked_permissions=set(), approval_required_permissions=set()
    )
    for permission in (ToolPermission.SHELL, ToolPermission.WRITE):
        tool = ToolDefinition(
            name="probe", description="Probe", permissions=[permission]
        )
        call = ToolCall(tool_call_id="call", tool_call={"name": "probe"})
        assert policy.authorize(tool, call).allowed
        assert not policy.authorize(tool, call).requires_approval
        assert not BasicToolSafetyPolicy().authorize(tool, call).allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_modes_are_scoped_and_keep_server_blocks_and_preflight(
    tmp_path: Path, persistent: bool
):
    store = (
        SQLiteToolPolicyStore(tmp_path / "runtime.sqlite3")
        if persistent
        else ToolPolicyStore()
    )
    register = ToolRegister()
    executed = []

    async def execute(arguments):
        executed.append(arguments)
        return {"ok": True}

    tool = ToolDefinition(
        name="write",
        description="Write",
        permissions=[ToolPermission.WRITE],
        safety_level=ToolSafetyLevel.SENSITIVE,
    )
    register.register(tool, execute)
    manager = ToolManager(register, policy_store=store)
    alice = PrincipalScope(owner_id="alice")
    bob = PrincipalScope(owner_id="bob")
    call = ToolCall(
        tool_call_id="call", tool_call={"name": "write"}, metadata={"owner_id": "alice"}
    )
    try:
        assert (
            manager.list_tool_policies(principal_scope=alice)[0].mode
            is ToolAccessMode.ASK
        )
        manager.set_tool_policy("write", ToolAccessMode.ALLOW, principal_scope=alice)
        await manager.execute(call)
        assert len(executed) == 1
        assert (
            manager.list_tool_policies(principal_scope=bob)[0].mode
            is ToolAccessMode.ASK
        )
        manager.set_tool_policy("write", ToolAccessMode.DENY, principal_scope=alice)
        assert manager.list_tools(principal_scope=alice) == []
        assert len(manager.list_tools(principal_scope=bob)) == 1
        with pytest.raises(ToolPolicyError):
            await manager.execute(
                call.model_copy(
                    update={"metadata": {"owner_id": "alice", "approved": True}}
                )
            )
        manager.set_tool_policy("write", None, principal_scope=alice)
        assert (
            manager.list_tool_policies(principal_scope=alice)[0].configured_mode is None
        )
        assert manager.authorize(call).requires_approval
        manager.set_tool_policy("write", ToolAccessMode.ASK, principal_scope=alice)
        register.register(
            tool.model_copy(
                update={
                    "permissions": [ToolPermission.READ],
                    "safety_level": ToolSafetyLevel.SAFE,
                }
            ),
            execute,
        )
        assert manager.authorize(call).requires_approval, (
            "source refresh must preserve overrides"
        )
        register.register(
            tool,
            execute,
            lambda _tool, _args: ToolSafetyDecision(
                allowed=False, reason="Outside root"
            ),
        )
        manager.set_tool_policy("write", ToolAccessMode.ALLOW, principal_scope=alice)
        with pytest.raises(ToolPolicyError):
            await manager.execute(call)
        register.register(
            tool.model_copy(update={"permissions": [ToolPermission.SHELL]}), execute
        )
        setting = manager.list_tool_policies(principal_scope=alice)[0]
        assert setting.mode is ToolAccessMode.DENY
        assert setting.blocked_reason
        with pytest.raises(ToolPolicyError):
            await manager.execute(call)
        assert len(executed) == 1
    finally:
        if isinstance(store, SQLiteToolPolicyStore):
            store.close()


@pytest.mark.asyncio
async def test_sqlite_restart_and_other_process_updates_are_visible(tmp_path: Path):
    path = tmp_path / "runtime.sqlite3"
    runtime = create_sqlite_runtime(path)
    interface = create_interface(runtime)
    scope = PrincipalScope(owner_id="alice")
    interface.tools.set_tool_policy(
        "generate_image", ToolAccessMode.DENY, principal_scope=scope
    )
    await runtime.close()
    restored = create_sqlite_runtime(path)
    create_interface(restored)
    other = SQLiteToolPolicyStore(path)
    try:
        assert restored.tools.list_tools(principal_scope=scope) == []
        assert (
            restored.tools.list_tool_policies(principal_scope=scope)[0].configured_mode
            is ToolAccessMode.DENY
        )
        other.set("generate_image", ToolAccessMode.ALLOW, principal_scope=scope)
        assert (
            restored.tools.list_tools(principal_scope=scope)[0].requires_approval
            is False
        )
        assert restored.tools.authorize(
            ToolCall(
                tool_call_id="call",
                tool_call={"name": "generate_image"},
                metadata={"owner_id": "alice"},
            )
        ).allowed
    finally:
        other.close()
        await restored.close()


@pytest.mark.asyncio
async def test_http_policy_permissions_ownership_reset_and_validation(tmp_path: Path):
    runtime = create_sqlite_runtime(tmp_path / "runtime.sqlite3")
    interface = create_interface(runtime)
    auth = ApiKeyHttpAuthDevice(
        [
            HttpApiKeyCredential(
                api_key=name,
                principal=Principal(
                    principal_id=name,
                    permissions=[
                        "tools:list",
                        *(["tools:configure"] if name != "reader" else []),
                    ],
                ),
            )
            for name in ("alice", "bob", "reader")
        ]
    )
    app = create_http_app(
        interface,
        auth_device=auth,
        authorized_interface_factory=lambda current, principal: (
            AuthorizedEvernightInterface(
                current, Authorizer(PermissionAuthPolicy()), principal
            )
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        try:
            headers = {"x-evernight-api-key": "alice"}
            response = await client.put(
                "/tools/generate_image/policy", json={"mode": "deny"}, headers=headers
            )
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert (await client.get("/tools", headers=headers)).json() == []
            response = await client.get("/tools/policies?owner_id=bob", headers=headers)
            assert response.json()[0]["mode"] == "deny"
            assert (
                await client.get(
                    "/tools/policies", headers={"x-evernight-api-key": "bob"}
                )
            ).json()[0]["configured_mode"] is None
            for method, kwargs in [
                ("PUT", {"json": {"mode": "allow"}}),
                ("DELETE", {}),
            ]:
                response = await client.request(
                    method,
                    "/tools/generate_image/policy",
                    headers={"x-evernight-api-key": "reader"},
                    **kwargs,
                )
                assert response.status_code == 403
            assert (
                await client.put(
                    "/tools/unknown/policy", json={"mode": "allow"}, headers=headers
                )
            ).status_code == 404
            assert (
                await client.put(
                    "/tools/generate_image/policy",
                    json={"mode": "oops"},
                    headers=headers,
                )
            ).status_code == 400
            assert (
                await client.put(
                    "/tools/generate_image/policy",
                    json={"mode": "allow", "owner_id": "bob"},
                    headers=headers,
                )
            ).status_code == 400
            response = await client.delete(
                "/tools/generate_image/policy", headers=headers
            )
            assert response.json()["configured_mode"] is None
            assert response.json()["mode"] == "ask"
        finally:
            await runtime.close()


@pytest.mark.asyncio
async def test_agent_rechecks_policy_after_approval_and_ignores_model_approval(
    tmp_path: Path,
):
    runtime = create_sqlite_runtime(tmp_path / "runtime.sqlite3")
    provider = ChatImageProvider()
    interface = await configure(runtime, provider)
    scope = PrincipalScope(owner_id="alice")
    app = AgentRunApplication(runtime)
    await runtime.contexts.create(
        Context(context_id="ctx", owner_id="alice"), principal_scope=scope
    )
    await runtime.contexts.create(
        Context(context_id="ctx-allowed", owner_id="alice"), principal_scope=scope
    )
    request = AgentRunRequest(
        context_id="ctx",
        provider_id="main",
        model_id="chat-model",
        owner_id="alice",
        messages=[message("Leaf")],
        tools=interface.tools.list_tools(principal_scope=scope),
        metadata={"run_id": "policy-run"},
    )
    try:
        state = await app.start(request, principal_scope=scope)
        assert state.status is AgentRunStatus.PAUSED
        runtime.tools.set_tool_policy(
            "generate_image", ToolAccessMode.DENY, principal_scope=scope
        )
        approval = state.pending_approval_requests[0]
        state = await app.resume(
            state.run_id,
            [
                ToolApprovalDecision(
                    approval_id=approval.approval_id,
                    tool_call_id=approval.tool_call_id,
                    status=ToolApprovalStatus.APPROVED,
                )
            ],
            principal_scope=scope,
        )
        assert not provider.requests
        assert any(step.error_type == "ToolPolicyError" for step in state.steps)
        assert provider.chat_requests[-1].tools == [], (
            "continued rounds must remove newly disabled tools"
        )
        runtime.tools.set_tool_policy(
            "generate_image", ToolAccessMode.ALLOW, principal_scope=scope
        )
        state = await app.start(
            request.model_copy(
                update={
                    "context_id": "ctx-allowed",
                    "metadata": {"run_id": "allowed-run"},
                }
            ),
            principal_scope=scope,
        )
        assert state.status is AgentRunStatus.FINISHED
        assert len(provider.requests) == 1
    finally:
        await app.close()
        await runtime.close()
