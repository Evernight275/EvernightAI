from EvernightAI.core.domain.tool_policy import ToolPolicyStore
from EvernightAI.core.schema.auth import PrincipalScope
from typing import Any
from dataclasses import dataclass
from EvernightAI.core.error.sandbox import SandboxError

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
    ToolPolicyStoreProtocol,
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
    ToolAccessMode,
    ToolPolicySummary,
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
        policy_store: ToolPolicyStoreProtocol | None = None,
    ) -> None:
        self._register = register
        self._safety_policy = safety_policy or BasicToolSafetyPolicy()
        self._policy_store = (
            policy_store if policy_store is not None else ToolPolicyStore()
        )

    def list_tools(
        self, *, principal_scope: PrincipalScope | None = None
    ) -> list[ToolDefinition]:
        tools = []
        for setting in self.list_tool_policies(principal_scope=principal_scope):
            if setting.mode is ToolAccessMode.DENY:
                continue
            tools.append(
                self._effective_definition(
                    setting.tool, setting.configured_mode
                ).model_copy(
                    update={"requires_approval": setting.mode is ToolAccessMode.ASK}
                )
            )
        return tools

    def list_tool_policies(
        self, *, principal_scope: PrincipalScope | None = None
    ) -> list[ToolPolicySummary]:
        return [
            self._policy_summary(tool, principal_scope)
            for tool in self._register.list_tools()
        ]

    def set_tool_policy(
        self,
        tool_name: str,
        mode: ToolAccessMode | None,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> ToolPolicySummary:
        tool = self._register.get(tool_name)
        if mode is None:
            self._policy_store.delete(tool_name, principal_scope=principal_scope)
        else:
            self._policy_store.set(tool_name, mode, principal_scope=principal_scope)
        return self._policy_summary(tool, principal_scope)

    def _policy_summary(
        self, tool: ToolDefinition, scope: PrincipalScope | None
    ) -> ToolPolicySummary:
        configured = self._policy_store.get(tool.name, principal_scope=scope)
        call = ToolCall(
            tool_call_id="policy-preview",
            tool_call={"name": tool.name, "arguments": {}},
            metadata={"owner_id": scope.owner_id if scope else None},
        )
        default = self._safety_policy.authorize(tool, call)
        effective = self._safety_policy.authorize(
            self._effective_definition(tool, configured), call
        )
        mode = self._decision_mode(effective)
        if configured is ToolAccessMode.DENY:
            mode = ToolAccessMode.DENY
        return ToolPolicySummary(
            tool=tool,
            mode=mode,
            default_mode=self._decision_mode(default),
            configured_mode=configured,
            blocked_reason=effective.reason
            if not effective.allowed and not effective.requires_approval
            else None,
        )

    def _decision_mode(self, decision: ToolSafetyDecision) -> ToolAccessMode:
        if decision.allowed:
            return ToolAccessMode.ALLOW
        return ToolAccessMode.ASK if decision.requires_approval else ToolAccessMode.DENY

    def _effective_definition(
        self, tool: ToolDefinition, mode: ToolAccessMode | None
    ) -> ToolDefinition:
        if mode not in (ToolAccessMode.ALLOW, ToolAccessMode.ASK):
            return tool
        return tool.model_copy(
            update={
                "approval_mode": ToolApprovalMode.NEVER
                if mode is ToolAccessMode.ALLOW
                else ToolApprovalMode.REQUIRED,
                "requires_approval": mode is ToolAccessMode.ASK,
            }
        )

    def authorize(self, call: ToolCall) -> ToolSafetyDecision:
        tool_name = self._get_tool_name(call.tool_call)
        arguments = self._execution_arguments(call)
        tool = self._register.get(tool_name)
        scope = PrincipalScope(owner_id=call.metadata.get("owner_id"))
        mode = self._policy_store.get(tool_name, principal_scope=scope)
        if mode is ToolAccessMode.DENY:
            return ToolSafetyDecision(
                allowed=False, reason="Tool is disabled by your tool policy"
            )
        tool = self._effective_definition(tool, mode)
        preflight_policy = self._register.get_preflight_policy(tool_name)
        if preflight_policy is not None:
            preflight_decision = preflight_policy(tool, arguments)
            if preflight_decision is not None and not preflight_decision.allowed:
                if not preflight_decision.requires_approval:
                    return preflight_decision
                tool = self._effective_definition(tool, ToolAccessMode.ASK)
                decision = self._safety_policy.authorize(tool, call)
                if decision.approval_request is not None:
                    decision.approval_request.reason = preflight_decision.reason
                    decision.approval_request.metadata.update(
                        preflight_decision.metadata
                    )
                if (
                    not decision.allowed
                    and decision.requires_approval
                    and (
                        call.approval is None
                        or call.approval.status is ToolApprovalStatus.REQUESTED
                    )
                ):
                    decision.reason = preflight_decision.reason
                return decision
        return self._safety_policy.authorize(tool, call)

    async def execute(self, call: ToolCall) -> ToolCallResult:
        tool_name = self._get_tool_name(call.tool_call)
        arguments = self._execution_arguments(call)
        decision = self.authorize(call)
        if not decision.allowed:
            raise ToolPolicyError(
                f"The tool {tool_name} call was rejected by policy",
                detail=decision.reason,
            )

        tool = self._register.get(tool_name)
        idempotency_key = call.metadata.get("idempotency_key")
        if (
            tool.idempotency_key_parameter is not None
            and isinstance(idempotency_key, str)
            and idempotency_key
        ):
            arguments[tool.idempotency_key_parameter] = idempotency_key

        executor = self._register.get_executor(tool_name)

        try:
            result = await executor(arguments)
        except (ToolExecutionError, SandboxError) as exc:
            raise ToolExecutionError(
                f"The tool {tool_name} execution failed: {exc}",
                detail=exc.detail,
                cause=exc,
            ) from exc
        except Exception as exc:
            raise ToolExecutionError(
                f"The tool {tool_name} execution failed", cause=exc
            ) from exc
        self._validate_result(tool_name, result)

        return ToolCallResult(
            tool_call_id=call.tool_call_id,
            tool_call_result=result,
        )

    def _execution_arguments(self, call: ToolCall) -> dict[str, Any]:
        arguments = dict(self._get_arguments(call.tool_call))
        tool = self._register.get(self._get_tool_name(call.tool_call))
        if tool.metadata.get("supports_execution_context"):
            arguments["_execution_context"] = {
                "owner_id": call.metadata.get("owner_id"),
                "session_id": call.metadata.get("session_id"),
                "run_id": call.metadata.get("run_id"),
                "tool_call_id": call.tool_call_id,
            }
            arguments.pop("_idempotency_key", None)
        if tool.metadata.get("supports_working_directory"):
            arguments.pop("_working_directory", None)
            directory = call.metadata.get("working_directory")
            if directory is not None:
                arguments["_working_directory"] = directory
        return arguments

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
        self._blocked_permissions = (
            blocked_permissions
            if blocked_permissions is not None
            else {
                ToolPermission.SHELL,
                ToolPermission.DESTRUCTIVE,
            }
        )
        self._approval_required_permissions = (
            approval_required_permissions
            if approval_required_permissions is not None
            else {
                ToolPermission.WRITE,
                ToolPermission.PROCESS,
                ToolPermission.NETWORK,
                ToolPermission.DATABASE,
                ToolPermission.EXTERNAL_API,
            }
        )

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
        if (
            approval is not None
            and approval.tool_call_id == call.tool_call_id
            and approval.status
            in (ToolApprovalStatus.DENIED, ToolApprovalStatus.EXPIRED)
        ):
            return ToolSafetyDecision(
                allowed=False,
                reason=approval.reason or f"Tool approval {approval.status.value}",
                requires_approval=True,
                approval_request=self._approval_request(tool, call),
            )
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
                metadata={"working_directory": call.metadata["working_directory"]}
                if tool.metadata.get("supports_working_directory")
                and call.metadata.get("working_directory") is not None
                else {},
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
            metadata={"working_directory": call.metadata["working_directory"]}
            if tool.metadata.get("supports_working_directory")
            and call.metadata.get("working_directory") is not None
            else {},
        )
