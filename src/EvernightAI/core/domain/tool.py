from typing import Any
from dataclasses import dataclass

from EvernightAI.core.error.tool import (
    ToolExecutionError,
    ToolInputError,
    ToolNotFoundError,
    ToolPolicyError,
    ToolResultError,
    ToolStateError,
)
from EvernightAI.core.protocol.tool import (
    ToolExecutorProtocol,
    ToolManageProtocol,
    ToolPreflightPolicy,
    ToolRegistration,
    ToolRegisterProtocol,
    ToolSafetyPolicyProtocol,
)
from EvernightAI.core.schema.tool import (
    ToolCall,
    ToolApprovalRequest,
    ToolApprovalMode,
    ToolApprovalStatus,
    ToolCallResult,
    ToolDefinition,
    ToolPermission,
    ToolSafetyDecision,
    ToolSafetyLevel,
)


@dataclass(frozen=True)
class _ToolRegisterSnapshot:
    tools: dict[str, ToolDefinition]
    executors: dict[str, ToolExecutorProtocol]
    preflight_policies: dict[str, ToolPreflightPolicy]
    source_owners: dict[str, str]


class ToolRegister(ToolRegisterProtocol):
    def __init__(self) -> None:
        self._snapshot = _ToolRegisterSnapshot({}, {}, {}, {})

    def register(
        self,
        tool: ToolDefinition,
        executor: ToolExecutorProtocol,
        preflight_policy: ToolPreflightPolicy | None = None,
    ) -> None:
        snapshot = self._snapshot
        owner = snapshot.source_owners.get(tool.name)
        if owner is not None:
            raise ToolStateError(f"The tool {tool.name} is managed by source {owner}")
        tools = dict(snapshot.tools)
        executors = dict(snapshot.executors)
        preflight_policies = dict(snapshot.preflight_policies)
        tools[tool.name] = tool
        executors[tool.name] = executor
        if preflight_policy is None:
            preflight_policies.pop(tool.name, None)
        else:
            preflight_policies[tool.name] = preflight_policy
        self._snapshot = _ToolRegisterSnapshot(
            tools,
            executors,
            preflight_policies,
            dict(snapshot.source_owners),
        )

    def unregister(self, tool_name: str) -> None:
        if not self.has(tool_name):
            raise ToolNotFoundError(f"The tool {tool_name} is not registered")
        snapshot = self._snapshot
        owner = snapshot.source_owners.get(tool_name)
        if owner is not None:
            raise ToolStateError(f"The tool {tool_name} is managed by source {owner}")
        tools = dict(snapshot.tools)
        executors = dict(snapshot.executors)
        preflight_policies = dict(snapshot.preflight_policies)
        tools.pop(tool_name, None)
        executors.pop(tool_name, None)
        preflight_policies.pop(tool_name, None)
        self._snapshot = _ToolRegisterSnapshot(
            tools,
            executors,
            preflight_policies,
            dict(snapshot.source_owners),
        )

    def replace_source(
        self,
        source_id: str,
        registrations: list[ToolRegistration],
    ) -> None:
        if not source_id:
            raise ToolStateError("The tool source id must not be empty")
        names = [registration.tool.name for registration in registrations]
        if len(names) != len(set(names)):
            raise ToolStateError(
                f"The tool source {source_id} contains duplicate tool names"
            )

        snapshot = self._snapshot
        conflicts = [
            name
            for name in names
            if name in snapshot.tools and snapshot.source_owners.get(name) != source_id
        ]
        if conflicts:
            raise ToolStateError(
                f"The tool source {source_id} conflicts with registered tools",
                detail=", ".join(sorted(conflicts)),
            )

        tools = dict(snapshot.tools)
        executors = dict(snapshot.executors)
        preflight_policies = dict(snapshot.preflight_policies)
        source_owners = dict(snapshot.source_owners)
        owned_names = [
            name for name, owner in source_owners.items() if owner == source_id
        ]
        for name in owned_names:
            tools.pop(name, None)
            executors.pop(name, None)
            preflight_policies.pop(name, None)
            source_owners.pop(name, None)

        for registration in registrations:
            name = registration.tool.name
            tools[name] = registration.tool
            executors[name] = registration.executor
            if registration.preflight_policy is None:
                preflight_policies.pop(name, None)
            else:
                preflight_policies[name] = registration.preflight_policy
            source_owners[name] = source_id

        self._snapshot = _ToolRegisterSnapshot(
            tools,
            executors,
            preflight_policies,
            source_owners,
        )

    def get(self, tool_name: str) -> ToolDefinition:
        if self.has(tool_name):
            return self._snapshot.tools[tool_name]
        raise ToolNotFoundError(f"The tool {tool_name} is not found")

    def get_executor(self, tool_name: str) -> ToolExecutorProtocol:
        if self.has(tool_name):
            return self._snapshot.executors[tool_name]
        raise ToolNotFoundError(f"The tool {tool_name} is not registered")

    def get_preflight_policy(
        self,
        tool_name: str,
    ) -> ToolPreflightPolicy | None:
        self.get(tool_name)
        return self._snapshot.preflight_policies.get(tool_name)

    def has(self, tool_name: str) -> bool:
        snapshot = self._snapshot
        return tool_name in snapshot.tools and tool_name in snapshot.executors

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._snapshot.tools.values())


class ToolManager(ToolManageProtocol):
    def __init__(
        self,
        register: ToolRegisterProtocol,
        safety_policy: ToolSafetyPolicyProtocol | None = None,
    ) -> None:
        self._register = register
        self._safety_policy = safety_policy or BasicToolSafetyPolicy()

    def list_tools(self) -> list[ToolDefinition]:
        return self._register.list_tools()

    def authorize(self, call: ToolCall) -> ToolSafetyDecision:
        tool_name = self._get_tool_name(call.tool_call)
        arguments = self._get_arguments(call.tool_call)
        tool = self._register.get(tool_name)
        preflight_policy = self._register.get_preflight_policy(tool_name)
        if preflight_policy is not None:
            preflight_decision = preflight_policy(tool, arguments)
            if preflight_decision is not None and not preflight_decision.allowed:
                return preflight_decision
        return self._safety_policy.authorize(tool, call)

    async def execute(self, call: ToolCall) -> ToolCallResult:
        tool_name = self._get_tool_name(call.tool_call)
        arguments = self._get_arguments(call.tool_call)
        decision = self.authorize(call)
        if not decision.allowed:
            raise ToolPolicyError(
                f"The tool {tool_name} call was rejected by policy",
                detail=decision.reason,
            )

        executor = self._register.get_executor(tool_name)

        try:
            result = await executor(arguments)
        except Exception as exc:
            raise ToolExecutionError(
                f"The tool {tool_name} execution failed", cause=exc
            ) from exc
        self._validate_result(tool_name, result)

        return ToolCallResult(
            tool_call_id=call.tool_call_id,
            tool_call_result=result,
        )

    def _get_tool_name(self, tool_call: dict[str, Any]) -> str:
        tool_name = tool_call.get("tool_name") or tool_call.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            raise ToolInputError("The tool call must include a tool name")
        return tool_name

    def _get_arguments(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        arguments = tool_call.get("arguments", tool_call.get("args", {}))
        if not isinstance(arguments, dict):
            raise ToolInputError("The tool call arguments must be a dictionary")
        return arguments

    def _validate_result(self, tool_name: str, result: object) -> None:
        if not isinstance(result, dict):
            raise ToolResultError(f"The tool {tool_name} result must be a dictionary")
        if not all(isinstance(key, str) for key in result):
            raise ToolResultError(f"The tool {tool_name} result keys must be strings")


class BasicToolSafetyPolicy(ToolSafetyPolicyProtocol):
    def __init__(
        self,
        *,
        blocked_permissions: set[ToolPermission] | None = None,
        approval_required_permissions: set[ToolPermission] | None = None,
    ) -> None:
        self._blocked_permissions = blocked_permissions or {
            ToolPermission.SHELL,
            ToolPermission.DESTRUCTIVE,
        }
        self._approval_required_permissions = approval_required_permissions or {
            ToolPermission.WRITE,
            ToolPermission.PROCESS,
            ToolPermission.NETWORK,
            ToolPermission.DATABASE,
            ToolPermission.EXTERNAL_API,
        }

    def authorize(
        self,
        tool: ToolDefinition,
        call: ToolCall,
    ) -> ToolSafetyDecision:
        permissions = set(tool.permissions)
        blocked = permissions & self._blocked_permissions
        if blocked:
            return ToolSafetyDecision(
                allowed=False,
                reason=f"Blocked permissions: {self._format_permissions(blocked)}",
            )

        if tool.approval_mode is ToolApprovalMode.REQUIRED:
            requires_approval = True
        elif tool.approval_mode is ToolApprovalMode.NEVER:
            requires_approval = False
        else:
            requires_approval = (
                tool.requires_approval
                or tool.safety_level is not ToolSafetyLevel.SAFE
                or bool(permissions & self._approval_required_permissions)
            )
        approval = call.approval
        approved = (
            approval is not None
            and approval.tool_call_id == call.tool_call_id
            and approval.status is ToolApprovalStatus.APPROVED
        ) or call.metadata.get("approved") is True
        if requires_approval and not approved:
            if approval is not None:
                return ToolSafetyDecision(
                    allowed=False,
                    reason=approval.reason or f"Tool approval {approval.status.value}",
                    requires_approval=True,
                    approval_request=self._approval_request(tool, call),
                    metadata={
                        "approval_status": approval.status.value,
                        "approval_id": approval.approval_id,
                    },
                )

            return ToolSafetyDecision(
                allowed=False,
                reason="Tool call requires approval",
                requires_approval=True,
                approval_request=self._approval_request(tool, call),
            )

        return ToolSafetyDecision(
            allowed=True,
            requires_approval=requires_approval,
            approval_request=(
                self._approval_request(tool, call) if requires_approval else None
            ),
            metadata={
                "policy": self.__class__.__name__,
                "approved": approved,
                "approval_id": approval.approval_id if approval is not None else None,
            },
        )

    def _format_permissions(self, permissions: set[ToolPermission]) -> str:
        return ", ".join(sorted(permission.value for permission in permissions))

    def _approval_request(
        self,
        tool: ToolDefinition,
        call: ToolCall,
    ) -> ToolApprovalRequest:
        return ToolApprovalRequest(
            approval_id=f"{call.tool_call_id}:approval",
            tool_call_id=call.tool_call_id,
            tool_name=tool.name,
            tool_call=dict(call.tool_call),
            permissions=list(tool.permissions),
            safety_level=tool.safety_level,
            reason="Tool call requires approval",
        )
