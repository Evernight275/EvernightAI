from EvernightAI.core.schema.sandbox import SandboxExecutionResult
from EvernightAI.core.error.base import (
    ConfigurationError,
    EvernightAIError,
    RequestError,
    ResponseError,
    ValidationError,
)


class SandboxError(EvernightAIError):
    """
    沙盒错误
    """

    pass


class SandboxInputError(SandboxError, ValidationError):
    """
    沙盒输入错误
    """

    pass


class SandboxConfigurationError(SandboxError, ConfigurationError):
    """
    沙盒配置错误
    """

    pass


class SandboxExecutionError(SandboxError, RequestError):
    """
    沙盒执行错误
    """

    pass


class SandboxTimeoutError(SandboxExecutionError):
    """
    沙盒超时错误，携带超时前已收集的输出
    """

    def __init__(
        self,
        message: str,
        *,
        result: SandboxExecutionResult,
        cause: Exception | None = None,
    ) -> None:
        parts = [
            f"{name} before timeout:\n{text}"
            for name, text in (("stdout", result.stdout), ("stderr", result.stderr))
            if text
        ]
        super().__init__(message, detail="\n".join(parts) or None, cause=cause)
        self.result = result


class SandboxPolicyError(SandboxExecutionError):
    """
    沙盒策略错误
    """

    pass


class SandboxResultError(SandboxError, ResponseError):
    """
    沙盒结果错误
    """

    pass
