from EvernightAI.core.schema.tool import (
    ToolCall,
    ToolCallResult,
    ToolDefinition,
    ToolSafetyDecision,
    ToolAccessMode,
    ToolPolicySummary,
)
from EvernightAI.core.schema.auth import PrincipalScope
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

ToolExecutorProtocol = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ToolPreflightPolicy = Callable[
    [ToolDefinition, dict[str, Any]],
    ToolSafetyDecision | None,
]


@dataclass(frozen=True)
class ToolRegistration:
    tool: ToolDefinition
    executor: ToolExecutorProtocol
    preflight_policy: ToolPreflightPolicy | None = None


class ToolSafetyPolicyProtocol(Protocol):
    """
    工具安全策略协议
    """

    def authorize(
        self,
        tool: ToolDefinition,
        call: ToolCall,
    ) -> ToolSafetyDecision: ...


class ToolManageProtocol(Protocol):
    """
    工具管理协议
    """

    def list_tools(
        self, *, principal_scope: PrincipalScope | None = None
    ) -> list[ToolDefinition]: ...

    def list_tool_policies(
        self, *, principal_scope: PrincipalScope | None = None
    ) -> list[ToolPolicySummary]: ...

    def set_tool_policy(
        self,
        tool_name: str,
        mode: ToolAccessMode | None,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> ToolPolicySummary: ...

    def authorize(self, call: ToolCall) -> ToolSafetyDecision: ...

    async def execute(self, call: ToolCall) -> ToolCallResult: ...


class ToolRegisterProtocol(Protocol):
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

    def replace_source(
        self,
        source_id: str,
        registrations: list[ToolRegistration],
    ) -> None: ...

    def get(self, tool_name: str) -> ToolDefinition: ...

    def get_executor(self, tool_name: str) -> ToolExecutorProtocol: ...

    def get_preflight_policy(
        self,
        tool_name: str,
    ) -> ToolPreflightPolicy | None: ...

    def has(self, tool_name: str) -> bool: ...

    def list_tools(self) -> list[ToolDefinition]: ...


class ToolSourceProtocol(Protocol):
    """Load tools from an external source into a runtime register."""

    async def load(self, register: ToolRegisterProtocol) -> None: ...

    async def refresh(self) -> None: ...

    def is_ready(self) -> bool: ...

    async def close(self) -> None: ...


class ToolPolicyStoreProtocol(Protocol):
    def get(
        self, tool_name: str, *, principal_scope: PrincipalScope | None = None
    ) -> ToolAccessMode | None: ...

    def set(
        self,
        tool_name: str,
        mode: ToolAccessMode,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    def delete(
        self, tool_name: str, *, principal_scope: PrincipalScope | None = None
    ) -> None: ...
