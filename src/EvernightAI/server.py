import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from EvernightAI.application.bootstrap import create_interface
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.infra.bootstrap import create_sqlite_runtime
from EvernightAI.interface.cli.schema import EvernightConfig
from EvernightAI.interface.http.app import create_http_app


DEFAULT_DATABASE_PATH = Path(".evernight") / "runtime.sqlite3"


def create_app(
    *,
    database_path: str | Path | None = None,
    filesystem_root: str | Path | None = None,
    close_on_shutdown: bool = True,
) -> FastAPI:
    runtime = create_sqlite_runtime(
        database_path or _env_path("EVERNIGHTAI_DATABASE_PATH", DEFAULT_DATABASE_PATH),
        filesystem_root=filesystem_root or _env_optional_path(
            "EVERNIGHTAI_FILESYSTEM_ROOT"
        ),
        allow_file_overwrite=_env_bool("EVERNIGHTAI_ALLOW_FILE_OVERWRITE", False),
        shell_allowed_commands=_env_optional_set("EVERNIGHTAI_SHELL_ALLOWED_COMMANDS"),
        shell_working_directory=_env_optional_path(
            "EVERNIGHTAI_SHELL_WORKING_DIRECTORY"
        ),
        shell_timeout_seconds=_env_float("EVERNIGHTAI_SHELL_TIMEOUT_SECONDS", 10.0),
        shell_max_output_chars=_env_int("EVERNIGHTAI_SHELL_MAX_OUTPUT_CHARS", 12000),
    )
    return create_http_app(
        create_interface(runtime),
        close_on_shutdown=close_on_shutdown,
    )


def create_runtime_from_config(config: EvernightConfig) -> RuntimeKernel:
    return create_sqlite_runtime(
        config.runtime.database_path,
        **_runtime_tool_options(config),
    )


def create_app_from_config(
    config: EvernightConfig,
    *,
    close_on_shutdown: bool = True,
) -> FastAPI:
    runtime = create_runtime_from_config(config)
    return create_http_app(
        create_interface(runtime),
        close_on_shutdown=close_on_shutdown,
    )


def _runtime_tool_options(config: EvernightConfig) -> dict[str, Any]:
    filesystem = config.tools.filesystem
    shell = config.tools.shell
    return {
        "filesystem_root": filesystem.root if filesystem.enabled else None,
        "max_read_chars": filesystem.max_read_chars,
        "max_directory_entries": filesystem.max_directory_entries,
        "allow_file_overwrite": filesystem.allow_write,
        "shell_allowed_commands": (
            set(shell.allowed_commands) if shell.enabled else None
        ),
        "shell_working_directory": shell.working_directory,
        "shell_timeout_seconds": shell.timeout_seconds,
        "shell_max_output_chars": shell.max_output_chars,
    }


def main() -> None:
    uvicorn.run(
        "EvernightAI.server:create_app",
        factory=True,
        host=os.getenv("EVERNIGHTAI_HTTP_HOST", "127.0.0.1"),
        port=_env_int("EVERNIGHTAI_HTTP_PORT", 8000),
        reload=_env_bool("EVERNIGHTAI_HTTP_RELOAD", False),
    )


def _env_path(name: str, default: str | Path) -> str | Path:
    return os.getenv(name) or default


def _env_optional_path(name: str) -> str | Path | None:
    value = os.getenv(name)
    if value is None or value == "":
        return None

    return value


def _env_optional_set(name: str) -> set[str] | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None

    return {
        item.strip()
        for item in value.split(",")
        if item.strip()
    }


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default

    return value.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default

    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default

    return float(value)


if __name__ == "__main__":
    main()
