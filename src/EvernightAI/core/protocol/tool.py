from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    RegisterProtocol,
    ResponsibilityProtocol,
    ManageProtocol,
)
from EvernightAI.core.schema.tool import (
    ToolCall,
    ToolCallResult,
    ToolDefinition,
    ToolSafetyDecision,
)
from collections.abc import Awaitable, Callable
from typing import Any

ToolExecutorProtocol = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ToolPreflightPolicy = Callable[
    [ToolDefinition, dict[str, Any]],
    ToolSafetyDecision | None,
]


class ToolProtocol(EvernightAIProtocol):
    """
    工具协议
    """

    ...


class ToolExecuteProtocol(ToolProtocol, ResponsibilityProtocol):
    """
    工具执行协议
    """

    async def execute(self, call: ToolCall) -> ToolCallResult: ...


class ToolSafetyPolicyProtocol(ToolProtocol, ResponsibilityProtocol):
    """
    工具安全策略协议
    """

    def authorize(
        self,
        tool: ToolDefinition,
        call: ToolCall,
    ) -> ToolSafetyDecision: ...


class ToolManageProtocol(ToolProtocol, ManageProtocol):
    """
    工具管理协议
    """

    def list_tools(self) -> list[ToolDefinition]: ...

    def authorize(self, call: ToolCall) -> ToolSafetyDecision: ...

    async def execute(self, call: ToolCall) -> ToolCallResult: ...


class ToolRegisterProtocol(ToolProtocol, RegisterProtocol):
    """
    工具注册协议
    """

    def register(
        self,
        tool: ToolDefinition,
        executor: ToolExecutorProtocol,
        preflight_policy: ToolPreflightPolicy | None = None,
    ) -> None: ...

    def unregister(self, tool_name: str) -> None: ...

    def get(self, tool_name: str) -> ToolDefinition: ...

    def get_executor(self, tool_name: str) -> ToolExecutorProtocol: ...

    def get_preflight_policy(
        self,
        tool_name: str,
    ) -> ToolPreflightPolicy | None: ...

    def has(self, tool_name: str) -> bool: ...

    def list_tools(self) -> list[ToolDefinition]: ...
