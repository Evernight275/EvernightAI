from EvernightAI.core.error.base import (
    EvernightAIError,
    NotFoundError,
    StateError,
    ValidationError,
)


class ContextError(EvernightAIError):
    """上下文错误"""

    pass


class ContextInputError(ContextError, ValidationError):
    """上下文输入错误"""

    pass


class ContextNotFoundError(ContextError, NotFoundError):
    """上下文未找到错误"""

    pass


class ContextStateError(ContextError, StateError):
    """上下文状态错误"""

    pass
