from typing import Any

from EvernightAI.core.error.tool import (
    ToolExecutionError,
    ToolInputError,
    ToolNotFoundError,
    ToolPolicyError,
)
from EvernightAI.core.protocol.tool import (
    ToolExecutorProtocol,
    ToolManageProtocol,
    ToolRegisterProtocol,
    ToolSafetyPolicyProtocol,
)
from EvernightAI.core.schema.tool import (
    ToolCall,
    ToolCallResult,
    ToolDefinition,
    ToolPermission,
    ToolSafetyDecision,
    ToolSafetyLevel,
)


class ToolRegister(ToolRegisterProtocol):
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._executors: dict[str, ToolExecutorProtocol] = {}

    def register(
        self, tool: ToolDefinition, executor: ToolExecutorProtocol
    ) -> None:
        """注册工具"""
        self._tools[tool.name] = tool
        self._executors[tool.name] = executor

    def unregister(self, tool_name: str) -> None:
        """注销工具"""
        if not self.has(tool_name):
            raise ToolNotFoundError(f"The tool {tool_name} is not registered")
        self._tools.pop(tool_name, None)
        self._executors.pop(tool_name, None)

    def get(self, tool_name: str) -> ToolDefinition:
        """获取工具定义"""
        if self.has(tool_name):
            return self._tools[tool_name]
        raise ToolNotFoundError(f"The tool {tool_name} is not found")

    def get_executor(self, tool_name: str) -> ToolExecutorProtocol:
        """获取工具执行器"""
        if self.has(tool_name):
            return self._executors[tool_name]
        raise ToolNotFoundError(f"The tool {tool_name} is not registered")

    def has(self, tool_name: str) -> bool:
        """检查工具是否存在"""
        return tool_name in self._tools and tool_name in self._executors

    def list_tools(self) -> list[ToolDefinition]:
        """列出所有工具定义"""
        return list(self._tools.values())


class ToolManager(ToolManageProtocol):
    def __init__(
        self,
        register: ToolRegisterProtocol,
        safety_policy: ToolSafetyPolicyProtocol | None = None,
    ) -> None:
        self._register = register
        self._safety_policy = safety_policy or BasicToolSafetyPolicy()

    def list_tools(self) -> list[ToolDefinition]:
        """列出所有工具定义"""
        return self._register.list_tools()

    async def execute(self, call: ToolCall) -> ToolCallResult:
        """执行工具调用"""
        tool_name = self._get_tool_name(call.tool_call)
        arguments = self._get_arguments(call.tool_call)
        tool = self._register.get(tool_name)
        decision = self._safety_policy.authorize(tool, call)
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
            ToolPermission.FILESYSTEM,
            ToolPermission.DATABASE,
            ToolPermission.EXTERNAL_API,
        }

    def authorize(
        self,
        tool: ToolDefinition,
        call: ToolCall,
    ) -> ToolSafetyDecision:
        """授权工具调用"""
        permissions = set(tool.permissions)
        blocked = permissions & self._blocked_permissions
        if blocked:
            return ToolSafetyDecision(
                allowed=False,
                reason=f"Blocked permissions: {self._format_permissions(blocked)}",
            )

        requires_approval = (
            tool.requires_approval
            or tool.safety_level is not ToolSafetyLevel.SAFE
            or bool(permissions & self._approval_required_permissions)
        )
        if requires_approval and call.metadata.get("approved") is not True:
            return ToolSafetyDecision(
                allowed=False,
                reason="Tool call requires approval",
            )

        return ToolSafetyDecision(
            allowed=True,
            metadata={
                "policy": self.__class__.__name__,
                "approved": call.metadata.get("approved") is True,
            },
        )

    def _format_permissions(self, permissions: set[ToolPermission]) -> str:
        return ", ".join(sorted(permission.value for permission in permissions))
