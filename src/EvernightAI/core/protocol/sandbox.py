from typing import Protocol

from EvernightAI.core.schema.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxPolicyDecision,
)


class SandboxPolicyProtocol(Protocol):
    """
    沙盒策略协议
    """

    def authorize(self, request: SandboxExecutionRequest) -> SandboxPolicyDecision: ...


class SandboxExecuteProtocol(Protocol):
    """
    沙盒执行协议
    """

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult: ...
