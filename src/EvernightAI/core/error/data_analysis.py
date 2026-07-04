from EvernightAI.core.error.base import (
    EvernightAIError,
    NotFoundError,
    RequestError,
    ResponseError,
    ValidationError,
)


class DataAnalysisError(EvernightAIError):
    """
    数据统计分析错误
    """

    pass


class DataAnalysisInputError(DataAnalysisError, ValidationError):
    """
    数据统计分析输入错误
    """

    pass


class DataAnalysisNotFoundError(DataAnalysisError, NotFoundError):
    """
    数据统计分析资源未找到错误
    """

    pass


class DataStatisticsExecutionError(DataAnalysisError, RequestError):
    """
    数据统计执行错误
    """

    pass


class DataAnalysisExecutionError(DataAnalysisError, RequestError):
    """
    数据分析执行错误
    """

    pass


class DataAnalysisResultError(DataAnalysisError, ResponseError):
    """
    数据统计分析结果错误
    """

    pass
