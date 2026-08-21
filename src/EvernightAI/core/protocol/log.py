from EvernightAI.core.protocol.base import EvernightAIProtocol, RegisterProtocol
from EvernightAI.core.schema.log import Log, LogLevel


class LogProtocol(EvernightAIProtocol):
    """
    日志协议
    """

    ...


class LogRegisterProtocol(LogProtocol, RegisterProtocol):
    """
    跨接口运行日志注册协议
    """

    def append_log(self, log: Log) -> int: ...

    def list_logs(
        self,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
        level: LogLevel | None = None,
        trace_id: str | None = None,
        subject_kind: str | None = None,
        subject_id: str | None = None,
    ) -> list[Log]: ...

    def clear_logs(self) -> None: ...

    def prune_logs(
        self,
        *,
        older_than: str | None = None,
        keep_latest: int | None = None,
    ) -> int: ...
