from EvernightAI.core.error.base import (
    EvernightAIError,
    ValidationError,
    StateError,
    RequestError,
    ResponseError,
)


class ChatError(EvernightAIError):
    """
    聊天错误
    """


class ChatInputError(ChatError, ValidationError):
    """
    聊天输入错误
    """

    pass


class ChatToolCallError(ChatError, ResponseError):
    """
    聊天工具调用错误
    """

    pass


class ChatContextLengthError(ChatError, RequestError):
    """
    聊天上下文长度错误
    """

    pass


class ChatStreamError(ChatError, StateError):
    """
    聊天流错误
    """

    pass
