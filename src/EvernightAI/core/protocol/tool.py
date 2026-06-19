from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    RegisterProtocol,
    ResponsibilityProtocol,
    ManageProtocol,
)
from EvernightAI.core.schema.tool import ToolCall, ToolCallResult, ToolDefinition
from collections.abc import Awaitable, Callable
from typing import Any

ToolExecutorProtocol = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


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


class ToolManageProtocol(ToolProtocol, ManageProtocol):
    """
    工具管理协议
    """

    def list_tools(self) -> list[ToolDefinition]: ...

    async def execute(self, call: ToolCall) -> ToolCallResult: ...


class ToolRegisterProtocol(ToolProtocol, RegisterProtocol):
    """
    工具注册协议
    """

    def register(
        self, tool: ToolDefinition, executor: ToolExecutorProtocol
    ) -> None: ...

    def unregister(self, tool_name: str) -> None: ...

    def get(self, tool_name: str) -> ToolDefinition: ...

    def get_executor(self, tool_name: str) -> ToolExecutorProtocol: ...

    def has(self, tool_name: str) -> bool: ...

    def list_tools(self) -> list[ToolDefinition]: ...
