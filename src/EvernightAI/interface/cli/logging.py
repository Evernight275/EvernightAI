import logging
import logging.config
from typing import Any

from EvernightAI.interface.log_store import install_recent_log_handler


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
ANSI_RESET = "\033[0m"
ANSI_GRAY = "\033[90m"
ANSI_WHITE = "\033[37m"
ANSI_BOLD_RED = "\033[1;31m"

LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: ANSI_BOLD_RED,
    logging.CRITICAL: "\033[1;37;41m",
}


class EvernightLogFormatter(logging.Formatter):
    def __init__(self, *, use_color: bool = True) -> None:
        super().__init__(datefmt=LOG_DATE_FORMAT)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt)
        level = f"[{record.levelname.lower()}]"
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"

        if not self._use_color:
            return f"{timestamp} {level} {message}"

        level_color = LEVEL_COLORS.get(record.levelno, ANSI_WHITE)
        message_color = ANSI_BOLD_RED if record.levelno >= logging.ERROR else ANSI_WHITE
        return (
            f"{ANSI_GRAY}{timestamp}{ANSI_RESET} "
            f"{level_color}{level}{ANSI_RESET} "
            f"{message_color}{message}{ANSI_RESET}"
        )


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )
    for handler in logging.getLogger().handlers:
        handler.setFormatter(EvernightLogFormatter())
    install_recent_log_handler(level)


def uvicorn_log_config(level: str = "INFO") -> dict[str, Any]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "evernight": {
                "()": "EvernightAI.interface.cli.logging.EvernightLogFormatter",
            },
        },
        "handlers": {
            "default": {
                "formatter": "evernight",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "evernight",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "recent": {
                "class": "EvernightAI.interface.log_store.RecentLogHandler",
                "store": "ext://EvernightAI.interface.log_store.RECENT_LOG_STORE",
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["default", "recent"],
                "level": level,
                "propagate": False,
            },
            "uvicorn.error": {
                "level": level,
            },
            "uvicorn.access": {
                "handlers": ["access", "recent"],
                "level": level,
                "propagate": False,
            },
            "EvernightAI": {
                "handlers": ["default", "recent"],
                "level": level,
                "propagate": False,
            },
        },
    }
