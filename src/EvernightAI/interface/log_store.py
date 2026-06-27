import logging
from collections import deque
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class LogEntry(EvernightAISchema):
    index: int
    timestamp: datetime
    level: str
    logger: str
    message: str
    module: str | None = None
    function: str | None = None
    line: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecentLogStore:
    def __init__(self, *, capacity: int = 1000) -> None:
        self._entries: deque[LogEntry] = deque(maxlen=capacity)
        self._lock = RLock()
        self._next_index = 1

    def append(self, record: logging.LogRecord) -> None:
        with self._lock:
            entry = LogEntry(
                index=self._next_index,
                timestamp=datetime.fromtimestamp(record.created, tz=timezone.utc),
                level=record.levelname.lower(),
                logger=record.name,
                message=record.getMessage(),
                module=record.module,
                function=record.funcName,
                line=record.lineno,
                metadata=_record_metadata(record),
            )
            self._next_index += 1
            self._entries.append(entry)

    def list(self, *, limit: int = 200, after: int | None = None) -> list[LogEntry]:
        clean_limit = max(1, min(limit, self._entries.maxlen or limit))
        with self._lock:
            entries = list(self._entries)

        if after is not None:
            entries = [entry for entry in entries if entry.index > after]

        return entries[-clean_limit:]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class RecentLogHandler(logging.Handler):
    def __init__(self, store: RecentLogStore) -> None:
        super().__init__()
        self.store = store

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.store.append(record)
        except Exception:
            self.handleError(record)


RECENT_LOG_STORE = RecentLogStore()
RECENT_LOG_HANDLER_NAME = "evernight_recent_memory"


def install_recent_log_handler(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "name", "") == RECENT_LOG_HANDLER_NAME:
            handler.setLevel(level)
            return

    handler = RecentLogHandler(RECENT_LOG_STORE)
    handler.name = RECENT_LOG_HANDLER_NAME
    handler.setLevel(level)
    root.addHandler(handler)


def _record_metadata(record: logging.LogRecord) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if record.exc_info:
        metadata["exception"] = logging.Formatter().formatException(record.exc_info)
    if record.stack_info:
        metadata["stack"] = record.stack_info

    return metadata
