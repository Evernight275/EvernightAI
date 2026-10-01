from EvernightAI.core.error.base import ConflictError, NotFoundError, ValidationError


class ImageRecordNotFoundError(NotFoundError):
    pass


class ImageRecordConflictError(ConflictError):
    pass


class ImageHistoryInputError(ValidationError):
    pass
