from EvernightAI.core.error.base import (
    AuthorizationError,
    EvernightAIError,
    PermissionDeniedError,
)


class AuthError(EvernightAIError):
    pass


class AuthRequiredError(AuthError, AuthorizationError):
    pass


class AuthPermissionDeniedError(AuthError, PermissionDeniedError):
    pass
