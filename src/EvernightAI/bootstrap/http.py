import os
from pathlib import Path

from fastapi import FastAPI

from EvernightAI.bootstrap.config import create_unsecured_interface_from_config
from EvernightAI.bootstrap.interface import create_authorized_interface, create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.schema.auth import Principal
from EvernightAI.interface.cli.schema import EvernightConfig
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import ApiKeyHttpAuthDevice, HttpApiKeyCredential


DEFAULT_DATABASE_PATH = Path(".evernight") / "runtime.sqlite3"
DEFAULT_HTTP_AUTH_PRINCIPAL_ID = "http-api-key"


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
        auth_device=_env_auth_device(),
        authorized_interface_factory=_authorized_interface_factory(),
        close_on_shutdown=close_on_shutdown,
    )


def create_app_from_config(
    config: EvernightConfig,
    *,
    close_on_shutdown: bool = True,
) -> FastAPI:
    interface = create_unsecured_interface_from_config(config)

    async def register_configured_providers() -> None:
        for provider in config.providers:
            if provider.is_enabled:
                await interface.providers.create_provider(provider)

    return create_http_app(
        interface,
        auth_device=_config_auth_device(config),
        authorized_interface_factory=_authorized_interface_factory(),
        close_on_shutdown=close_on_shutdown,
        startup_handlers=[register_configured_providers],
    )


def _env_auth_device() -> ApiKeyHttpAuthDevice | None:
    api_key = os.getenv("EVERNIGHTAI_HTTP_API_KEY")
    if api_key is None or api_key == "":
        return None

    principal = Principal(
        principal_id=os.getenv(
            "EVERNIGHTAI_HTTP_AUTH_PRINCIPAL_ID",
            DEFAULT_HTTP_AUTH_PRINCIPAL_ID,
        ),
        permissions=_env_set("EVERNIGHTAI_HTTP_AUTH_PERMISSIONS") or ["*"],
    )
    return _api_key_auth_device(
        [HttpApiKeyCredential(api_key=api_key, principal=principal)]
    )


def _config_auth_device(config: EvernightConfig) -> ApiKeyHttpAuthDevice | None:
    if not config.auth.enabled:
        return None

    credentials = [
        HttpApiKeyCredential(
            api_key=principal.api_key,
            principal=Principal(
                principal_id=principal.principal_id,
                principal_type=principal.principal_type,
                roles=principal.roles,
                permissions=principal.permissions,
                metadata=principal.metadata,
            ),
        )
        for principal in config.auth.principals
        if principal.api_key is not None
    ]
    return _api_key_auth_device(credentials)


def _api_key_auth_device(
    credentials: list[HttpApiKeyCredential],
) -> ApiKeyHttpAuthDevice:
    return ApiKeyHttpAuthDevice(credentials)


def _authorized_interface_factory():
    authorizer = Authorizer(PermissionAuthPolicy())

    def factory(interface, principal):
        return create_authorized_interface(interface, authorizer, principal)

    return factory


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


def _env_set(name: str) -> list[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return []

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


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
