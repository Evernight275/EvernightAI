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
