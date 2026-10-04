from EvernightAI.core.error.base import (
    ConflictError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)


class ImageRecordNotFoundError(NotFoundError):
    pass


class ImageRecordConflictError(ConflictError):
    pass


class ImageHistoryInputError(ValidationError):
    pass


class ImageTaskNotFoundError(NotFoundError):
    pass


class ImageTaskConflictError(ConflictError):
    pass


class ImageTaskLimitError(RateLimitError):
    pass
