from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.trace import TraceSubject


class LogLevel(StrEnum):
    """日志级别。"""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Log(EvernightAISchema):
    """跨接口运行日志记录。

    Log面向排障和运维说明；TraceEvent面向结构化语义时间线。二者可以通过
    trace_id、span_id或subject关联，但不能互相替代。
    """

    sequence: int | None = Field(default=None, ge=1)
    occurred_at: datetime | None = None
    level: LogLevel
    source: str
    message: str
    trace_id: str | None = None
    span_id: str | None = None
    subject: TraceSubject | None = None
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
