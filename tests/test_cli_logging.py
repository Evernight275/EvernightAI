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
