from EvernightAI.core.error.base import (
    EvernightAIError,
    NotFoundError,
    StateError,
    ValidationError,
)


class MemoryError(EvernightAIError):
    """记忆错误"""

    pass


class MemoryInputError(MemoryError, ValidationError):
    """记忆输入错误"""

    pass


class MemoryNotFoundError(MemoryError, NotFoundError):
    """记忆未找到错误"""

    pass


class MemoryStateError(MemoryError, StateError):
    """记忆状态错误"""

    pass
