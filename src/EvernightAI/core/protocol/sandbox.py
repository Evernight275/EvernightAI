from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    ResponsibilityProtocol,
)
from EvernightAI.core.schema.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxPolicyDecision,
)


class SandboxProtocol(EvernightAIProtocol):
    """
    沙盒协议
    """

    ...


class SandboxPolicyProtocol(SandboxProtocol, ResponsibilityProtocol):
    """
    沙盒策略协议
    """

    def authorize(self, request: SandboxExecutionRequest) -> SandboxPolicyDecision: ...


class SandboxExecuteProtocol(SandboxProtocol, ResponsibilityProtocol):
    """
    沙盒执行协议
    """

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult: ...
