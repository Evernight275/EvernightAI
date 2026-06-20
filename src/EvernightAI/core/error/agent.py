from EvernightAI.core.error.base import EvernightAIError, StateError


class AgentError(EvernightAIError):
    """
    Agent错误
    """

    pass


class AgentStateError(AgentError, StateError):
    """
    Agent状态错误
    """

    pass
