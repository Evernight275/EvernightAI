from EvernightAI.core.error.base import (
    EvernightAIError,
    NotFoundError,
    StateError,
    ValidationError,
)


class SessionError(EvernightAIError):
    """
    会话错误
    """

    pass


class SessionInputError(SessionError, ValidationError):
    """
    会话输入错误
    """

    pass


class SessionNotFoundError(SessionError, NotFoundError):
    """
    会话未找到错误
    """

    pass


class SessionStateError(SessionError, StateError):
    """
    会话状态错误
    """

    pass
