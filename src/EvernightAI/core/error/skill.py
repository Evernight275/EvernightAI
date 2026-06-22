from EvernightAI.core.error.base import (
    ConfigurationError,
    EvernightAIError,
    NotFoundError,
    RequestError,
    ResponseError,
    StateError,
    ValidationError,
)


class SkillError(EvernightAIError):
    """
    技能错误
    """

    pass


class SkillInputError(SkillError, ValidationError):
    """
    技能输入错误
    """

    pass


class SkillNotFoundError(SkillError, NotFoundError):
    """
    技能未找到错误
    """

    pass


class SkillConfigurationError(SkillError, ConfigurationError):
    """
    技能配置错误
    """

    pass


class SkillRenderError(SkillError, RequestError):
    """
    技能渲染错误
    """

    pass


class SkillPromptError(SkillError, ResponseError):
    """
    技能提示词错误
    """

    pass


class SkillStateError(SkillError, StateError):
    """
    技能状态错误
    """

    pass
