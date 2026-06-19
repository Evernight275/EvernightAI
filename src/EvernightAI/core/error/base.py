class EvernightAIError(Exception):
    """
    错误基类
    """

    def __init__(
        self,
        message: str,
        detail: str | None = None,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.detail = detail
        self.cause = cause

    @property
    def error_type(self) -> str:
        """
        获取错误类型
        """
        return self.__class__.__name__


class ConfigurationError(EvernightAIError):
    """
    配置错误
    """

    pass


class ConflictError(EvernightAIError):
    """
    冲突错误
    """

    pass


class NotFoundError(EvernightAIError):
    """
    未找到错误
    """

    pass


class RateLimitError(EvernightAIError):
    """
    速率限制错误
    """

    pass


class UnsupportedError(EvernightAIError):
    """
    不支持错误
    """

    pass


class ValidationError(EvernightAIError):
    """
    校验错误
    """

    pass


class StateError(EvernightAIError):
    """
    状态错误
    """

    pass


class DependencyError(EvernightAIError):
    """
    依赖错误
    """

    pass


class RequestError(EvernightAIError):
    """
    请求错误
    """

    pass


class RequestTimeoutError(RequestError):
    """
    请求超时错误
    """

    pass


class AuthorizationError(RequestError):
    """
    授权错误
    """

    pass


class ResponseError(EvernightAIError):
    """
    响应错误
    """

    pass
