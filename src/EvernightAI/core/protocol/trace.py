from EvernightAI.core.protocol.base import EvernightAIProtocol, RegisterProtocol
from EvernightAI.core.schema.trace import TraceEvent


class TraceProtocol(EvernightAIProtocol):
    """
    追踪协议
    """

    ...


class TraceRegisterProtocol(TraceProtocol, RegisterProtocol):
    """
    跨领域语义追踪事件注册协议
    """

    def append_event(self, event: TraceEvent) -> int: ...

    def list_events(
        self,
        *,
        trace_id: str | None = None,
        after_sequence: int = 0,
        limit: int | None = None,
        event_type: str | None = None,
        subject_kind: str | None = None,
        subject_id: str | None = None,
    ) -> list[TraceEvent]: ...

    def clear_events(self, *, trace_id: str | None = None) -> None: ...

    def prune_events(
        self,
        *,
        older_than: str | None = None,
        keep_latest: int | None = None,
    ) -> int: ...
