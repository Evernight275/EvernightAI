import os
from pathlib import Path

from fastapi import FastAPI

from EvernightAI.bootstrap.config import create_interface_from_config
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
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


def create_app_from_config(
    config: EvernightConfig,
    *,
    close_on_shutdown: bool = True,
) -> FastAPI:
    interface = create_interface_from_config(config)

    async def register_configured_providers() -> None:
        for provider in config.providers:
            if provider.is_enabled:
                await interface.providers.create_provider(provider)

    return create_http_app(
        interface,
        close_on_shutdown=close_on_shutdown,
        startup_handlers=[register_configured_providers],
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
