import logging
from collections import deque
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from EvernightAI.core.schema.log import Log, LogLevel


class RecentLogStore:
    def __init__(self, *, capacity: int = 1000) -> None:
        self._entries: deque[Log] = deque(maxlen=capacity)
        self._lock = RLock()
        self._next_sequence = 1

    def append(self, record: logging.LogRecord) -> None:
        with self._lock:
            entry = Log(
                sequence=self._next_sequence,
                occurred_at=datetime.fromtimestamp(record.created, tz=timezone.utc),
                level=_record_level(record),
                source=record.name,
                message=record.getMessage(),
                metadata=_record_metadata(record),
            )
            self._next_sequence += 1
            self._entries.append(entry)

    def list(self, *, limit: int = 200, after: int | None = None) -> list[Log]:
        clean_limit = max(1, min(limit, self._entries.maxlen or limit))
        with self._lock:
            entries = list(self._entries)

        if after is not None:
            entries = [entry for entry in entries if (entry.sequence or 0) > after]

        return entries[-clean_limit:]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._next_sequence = 1


class RecentLogHandler(logging.Handler):
    def __init__(self, store: RecentLogStore) -> None:
        super().__init__()
        self.store = store

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if _should_skip_recent_log(record):
                return
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
    for key, value in (
        ("module", record.module),
        ("function", record.funcName),
        ("line", record.lineno),
    ):
        if value is not None:
            metadata[key] = value
    for key in (
        "request_id",
        "session_id",
        "run_id",
        "provider_id",
        "model_id",
        "tool_name",
        "http_method",
        "http_path",
        "http_status",
        "duration_ms",
        "success",
        "error_type",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_prompt_tokens",
        "cache_write_prompt_tokens",
        "provider_calls_total",
        "provider_errors_total",
        "provider_error_rate",
    ):
        value = getattr(record, key, None)
        if value is not None:
            metadata[key] = value
    if record.exc_info:
        metadata["exception"] = logging.Formatter().formatException(record.exc_info)
    if record.stack_info:
        metadata["stack"] = record.stack_info

    return metadata


def _record_level(record: logging.LogRecord) -> LogLevel:
    level_name = record.levelname.lower()
    try:
        return LogLevel(level_name)
    except ValueError:
        return LogLevel.INFO


def _should_skip_recent_log(record: logging.LogRecord) -> bool:
    if record.name == "httpx" and record.levelno < logging.WARNING:
        return True

    if record.name != "uvicorn.access":
        return False

    method, _path, status_code = _uvicorn_access_parts(record)
    if status_code is None or status_code >= 400:
        return False

    return method in {"GET", "HEAD", "OPTIONS", "POST"}


def _uvicorn_access_parts(
    record: logging.LogRecord,
) -> tuple[str | None, str, int | None]:
    if isinstance(record.args, tuple) and len(record.args) >= 5:
        method = record.args[1]
        path = record.args[2]
        status_code = record.args[4]
        return (
            method if isinstance(method, str) else None,
            path if isinstance(path, str) else "",
            status_code if isinstance(status_code, int) else None,
        )

    message = record.getMessage()
    parts = message.split('"')
    if len(parts) < 3:
        return None, "", None

    request_line = parts[1].split()
    method = request_line[0] if len(request_line) >= 1 else None
    path = request_line[1] if len(request_line) >= 2 else ""
    status_text = parts[2].strip().split(" ", 1)[0]
    try:
        status_code = int(status_text)
    except ValueError:
        status_code = None

    return method, path, status_code
