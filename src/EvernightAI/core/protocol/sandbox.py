from typing import Protocol, runtime_checkable

from EvernightAI.core.schema.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxOutputEvent,
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


class SandboxProcessProtocol(Protocol):
    """
    沙盒中持续运行的进程
    """

    @property
    def returncode(self) -> int | None: ...

    async def read(self) -> SandboxOutputEvent | None:
        """Next output event, or None once stdout and stderr are closed."""
        ...

    async def write_stdin(self, text: str) -> None: ...

    async def close_stdin(self) -> None: ...

    async def wait(self) -> int: ...

    async def terminate(self) -> None:
        """Stop the process and everything it started."""
        ...


@runtime_checkable
class SandboxSpawnProtocol(Protocol):
    """
    启动不等待结束的沙盒进程
    """

    async def spawn(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxProcessProtocol: ...
