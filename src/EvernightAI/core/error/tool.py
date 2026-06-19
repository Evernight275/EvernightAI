from EvernightAI.core.error.base import (
    EvernightAIError,
    ValidationError,
    StateError,
    RequestError,
    ResponseError,
    NotFoundError,
    ConfigurationError,
)


class ToolError(EvernightAIError):
    """
    工具错误
    """

    pass


class ToolInputError(ToolError, ValidationError):
    """
    工具输入错误
    """

    pass


class ToolNotFoundError(ToolError, NotFoundError):
    """
    工具未找到错误
    """

    pass


class ToolConfigurationError(ToolError, ConfigurationError):
    """
    工具配置错误
    """

    pass


class ToolExecutionError(ToolError, RequestError):
    """
    工具执行错误
    """

    pass


class ToolPolicyError(ToolExecutionError):
    """
    工具策略错误
    """

    pass


class ToolResultError(ToolError, ResponseError):
    """
    工具结果错误
    """

    pass


class ToolStateError(ToolError, StateError):
    """
    工具状态错误
    """

    pass
