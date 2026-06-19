from EvernightAI.core.error.base import (
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    EvernightAIError,
    NotFoundError,
    RateLimitError,
    RequestError,
    RequestTimeoutError,
    ResponseError,
    UnsupportedError,
)


class ProviderError(EvernightAIError):
    """提供商错误"""

    pass


class ProviderUnavailableError(ProviderError):
    """提供商不可用错误"""

    pass


class ProviderCapabilityUnsupportedError(ProviderError, UnsupportedError):
    """提供商能力不支持错误"""

    pass


class ProviderConfigurationError(ProviderError, ConfigurationError):
    """提供商配置错误"""

    pass


class ProviderAuthorizationError(ProviderError, AuthorizationError):
    """提供商授权错误"""

    pass


class ProviderConflictError(ProviderError, ConflictError):
    """提供商冲突错误"""

    pass


class ProviderNotFoundError(ProviderError, NotFoundError):
    """提供商未找到错误"""

    pass


class ProviderRateLimitError(ProviderError, RateLimitError):
    """提供商速率限制错误"""

    pass


class ProviderRequestError(ProviderError, RequestError):
    """提供商请求错误"""

    pass


class ProviderResponseError(ProviderError, ResponseError):
    """提供商响应错误"""

    pass


class ProviderRequestTimeoutError(ProviderRequestError, RequestTimeoutError):
    """提供商请求超时错误"""

    pass
