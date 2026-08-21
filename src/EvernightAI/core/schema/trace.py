from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


TraceEventType = TypeVar("TraceEventType", bound=str)


class TraceSubject(EvernightAISchema):
    """Trace事件关联的业务对象。"""

    kind: str
    subject_id: str | None = None
    owner_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceEvent(EvernightAISchema, Generic[TraceEventType]):
    """跨领域语义追踪事件。

    TraceEvent记录系统认为重要的业务事实。它不是日志文本，也不是某个
    agent run 的恢复快照；具体领域可以继承它并补充强类型载荷。
    """

    sequence: int | None = Field(default=None, ge=1)
    trace_id: str | None = None
    event_id: str | None = None
    parent_event_id: str | None = None
    occurred_at: datetime | None = None
    event_type: TraceEventType
    source: str | None = None
    subject: TraceSubject | None = None
    summary: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
