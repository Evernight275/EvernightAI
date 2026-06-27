import logging
import re

from EvernightAI.interface.cli.logging import (
    ANSI_BOLD_RED,
    ANSI_GRAY,
    ANSI_RESET,
    ANSI_WHITE,
    EvernightLogFormatter,
    uvicorn_log_config,
)
from EvernightAI.interface.log_store import RecentLogHandler, RecentLogStore


def make_record(level: int, message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="EvernightAI.test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_evernight_log_formatter_uses_timestamp_and_lowercase_level() -> None:
    record = make_record(logging.INFO, "hello")
    record.created = 1780000000.0

    message = EvernightLogFormatter(use_color=False).format(record)

    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[info\] hello",
        message,
    )


def test_evernight_log_formatter_colors_log_parts() -> None:
    record = make_record(logging.INFO, "hello")
    record.created = 1780000000.0

    message = EvernightLogFormatter().format(record)

    assert message.startswith(ANSI_GRAY)
    assert f"{ANSI_RESET} \033[32m[info]{ANSI_RESET} {ANSI_WHITE}hello{ANSI_RESET}" in message


def test_evernight_log_formatter_highlights_errors() -> None:
    record = logging.LogRecord(
        name="EvernightAI.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="failed",
        args=(),
        exc_info=None,
    )
    record.created = 1780000000.0

    message = EvernightLogFormatter().format(record)

    assert f"{ANSI_BOLD_RED}[error]{ANSI_RESET}" in message
    assert f"{ANSI_BOLD_RED}failed{ANSI_RESET}" in message


def test_uvicorn_log_config_uses_evernight_formatter() -> None:
    config = uvicorn_log_config()

    assert config["formatters"]["evernight"] == {
        "()": "EvernightAI.interface.cli.logging.EvernightLogFormatter",
    }
    assert config["handlers"]["default"]["formatter"] == "evernight"
    assert config["handlers"]["access"]["formatter"] == "evernight"
    assert config["handlers"]["recent"] == {
        "class": "EvernightAI.interface.log_store.RecentLogHandler",
        "store": "ext://EvernightAI.interface.log_store.RECENT_LOG_STORE",
    }
    assert "recent" in config["loggers"]["EvernightAI"]["handlers"]


def test_recent_log_store_keeps_recent_entries_and_filters_after_index() -> None:
    store = RecentLogStore(capacity=2)
    first = make_record(logging.INFO, "first")
    second = make_record(logging.WARNING, "second")
    third = make_record(logging.ERROR, "third")
    first.created = 1780000000.0
    second.created = 1780000001.0
    third.created = 1780000002.0

    store.append(first)
    store.append(second)
    store.append(third)

    entries = store.list(limit=10)
    assert [entry.message for entry in entries] == ["second", "third"]
    assert [entry.level for entry in entries] == ["warning", "error"]
    assert [entry.message for entry in store.list(after=2)] == ["third"]


def test_recent_log_handler_skips_successful_log_polling_access_logs() -> None:
    store = RecentLogStore()
    handler = RecentLogHandler(store)

    handler.emit(make_access_record("GET", "/logs?limit=500&after=1", 200))
    handler.emit(make_access_record("POST", "/logs/clear", 204))
    handler.emit(make_access_record("GET", "/logs?limit=500&after=1", 500))
    handler.emit(make_access_record("GET", "/sessions", 200))

    assert [
        entry.message
        for entry in store.list()
    ] == [
        '127.0.0.1:41800 - "GET /logs?limit=500&after=1 HTTP/1.1" 500',
        '127.0.0.1:41800 - "GET /sessions HTTP/1.1" 200',
    ]


def make_access_record(method: str, path: str, status_code: int) -> logging.LogRecord:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:41800", method, path, "1.1", status_code),
        exc_info=None,
    )
    record.created = 1780000000.0
    return record
