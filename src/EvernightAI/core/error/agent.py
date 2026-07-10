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


class AgentShutdownError(AgentError, StateError):
    """
    Agent关闭期间拒绝新运行
    """

    pass


class AgentRunTimeoutError(AgentError, StateError):
    """Agent运行超过执行超时。"""

    pass


class AgentRunCanceledError(AgentError, StateError):
    """Agent运行收到真实任务取消信号。"""

    pass
