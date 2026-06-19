from typing import Any

from EvernightAI.core.error.tool import (
    ToolExecutionError,
    ToolInputError,
    ToolNotFoundError,
)
from EvernightAI.core.protocol.tool import (
    ToolExecutorProtocol,
    ToolManageProtocol,
    ToolRegisterProtocol,
)
from EvernightAI.core.schema.tool import ToolCall, ToolCallResult, ToolDefinition


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
    def __init__(self, register: ToolRegisterProtocol) -> None:
        self._register = register

    def list_tools(self) -> list[ToolDefinition]:
        """列出所有工具定义"""
        return self._register.list_tools()

    async def execute(self, call: ToolCall) -> ToolCallResult:
        """执行工具调用"""
        tool_name = self._get_tool_name(call.tool_call)
        arguments = self._get_arguments(call.tool_call)
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
