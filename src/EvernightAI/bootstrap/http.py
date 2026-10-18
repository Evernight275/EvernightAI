import logging
import os
from pathlib import Path

from fastapi import FastAPI

from EvernightAI.bootstrap.config import (
    create_unsecured_interface_from_config,
    principal_for_user,
)
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.options import (
    BuiltinToolOptions,
    FilesystemToolOptions,
    ShellToolOptions,
)
from EvernightAI.bootstrap.runtime import (
    create_memory_strategy,
    create_memory_write_strategy,
    create_sqlite_runtime,
)
from EvernightAI.core.domain.api_key import ApiKeyManager, ManagedApiKeyAuthDevice
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.infra.adapters.api_key import SQLiteApiKeyRegister
from EvernightAI.interface.cli.config import load_config
from EvernightAI.interface.cli.schema import EvernightConfig
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import (
    ApiKeyHttpAuthDevice,
    CompositeHttpAuthDevice,
    HttpApiKeyCredential,
    HttpOAuthBearerCredential,
    HttpOAuthJwtConfig,
    HttpPasswordCredential,
    ManagedApiKeyHttpAuthDevice,
    OAuthBearerHttpAuthDevice,
    OAuthJwtBearerHttpAuthDevice,
    PasswordLoginHttpAuthDevice,
)
from EvernightAI.interface.http.protocol import HttpAuthDeviceProtocol

DEFAULT_DATABASE_PATH = Path(".evernight") / "runtime.sqlite3"
DEFAULT_HTTP_AUTH_PRINCIPAL_ID = "http-api-key"
DEFAULT_HTTP_OAUTH_PRINCIPAL_ID = "http-oauth"
CONFIG_PATH_ENV = "EVERNIGHTAI_CONFIG_PATH"

LOGGER = logging.getLogger(__name__)


def _default_static_files_path() -> Path | None:
    path = Path("frontend") / "dist"
    return path if path.is_dir() else None


def create_app(
    *,
    database_path: str | Path | None = None,
    filesystem_root: str | Path | None = None,
    static_files_path: str | Path | None = None,
    close_on_shutdown: bool = True,
) -> FastAPI:
    filesystem_root = filesystem_root or _env_optional_path(
        "EVERNIGHTAI_FILESYSTEM_ROOT"
    )
    shell_allowed_commands = _env_optional_set("EVERNIGHTAI_SHELL_ALLOWED_COMMANDS")
    tools = BuiltinToolOptions(
        filesystem=(
            FilesystemToolOptions(
                root=filesystem_root,
                allow_overwrite=_env_bool("EVERNIGHTAI_ALLOW_FILE_OVERWRITE", False),
            )
            if filesystem_root is not None
            else None
        ),
        shell=(
            ShellToolOptions(
                allowed_commands=shell_allowed_commands,
                blocked_commands=_env_optional_set(
                    "EVERNIGHTAI_SHELL_BLOCKED_COMMANDS"
                ),
                working_directory=_env_optional_path(
                    "EVERNIGHTAI_SHELL_WORKING_DIRECTORY"
                ),
                timeout_seconds=_env_float("EVERNIGHTAI_SHELL_TIMEOUT_SECONDS", 10.0),
                max_output_chars=_env_int("EVERNIGHTAI_SHELL_MAX_OUTPUT_CHARS", 12000),
                requires_approval=_env_bool("EVERNIGHTAI_SHELL_IS_NEED_APPROVAL", True),
            )
            if shell_allowed_commands is not None
            else None
        ),
    )
    runtime = create_sqlite_runtime(
        database_path or _env_path("EVERNIGHTAI_DATABASE_PATH", DEFAULT_DATABASE_PATH),
        tools=tools,
        trace_retention_days=_env_optional_int("EVERNIGHTAI_TRACE_RETENTION_DAYS", 30),
        trace_max_events=_env_optional_int("EVERNIGHTAI_TRACE_MAX_EVENTS", 100_000),
        memory_strategy=create_memory_strategy(
            os.getenv("EVERNIGHTAI_MEMORY_SELECTION_STRATEGY", "basic")
        ),
        memory_write_strategy=create_memory_write_strategy(
            os.getenv("EVERNIGHTAI_MEMORY_WRITE_STRATEGY", "basic")
        ),
    )
    auth_device = _env_auth_device()
    if auth_device is None:
        LOGGER.warning(
            "HTTP authentication is disabled: set EVERNIGHTAI_HTTP_API_KEY or "
            "EVERNIGHTAI_HTTP_OAUTH_ACCESS_TOKEN to require credentials"
        )
    return create_http_app(
        create_interface(runtime),
        auth_device=auth_device,
        workspace_directories=runtime.workspace_directories,
        authorized_interface_factory=_authorized_interface_factory(),
        close_on_shutdown=close_on_shutdown,
        initialize_handler=runtime.initialize,
        readiness_checker=lambda: runtime.is_ready,
        server_header=_env_optional_string(
            "EVERNIGHTAI_HTTP_SERVER_HEADER",
            "EvernightAI",
        ),
        static_files_path=(
            static_files_path
            or _env_optional_path("EVERNIGHTAI_HTTP_STATIC_FILES_PATH")
            or _default_static_files_path()
        ),
    )


def create_app_from_config_path() -> FastAPI:
    """App factory for uvicorn reload, which must import the app by name."""
    config_path = os.getenv(CONFIG_PATH_ENV)
    if not config_path:
        raise ConfigurationError(f"{CONFIG_PATH_ENV} is not set")
    return create_app_from_config(load_config(config_path))


def create_app_from_config(
    config: EvernightConfig,
    *,
    close_on_shutdown: bool = True,
) -> FastAPI:
    interface = create_unsecured_interface_from_config(config)
    runtime = interface.runtime

    async def register_configured_providers() -> None:
        stored_ids = (
            {
                provider.provider_id
                for provider in runtime.provider_config_store.list_configs()
            }
            if runtime.provider_config_store is not None
            else set()
        )
        for provider in config.providers:
            if provider.provider_id in stored_ids:
                LOGGER.info(
                    "Provider %s is already stored; its stored settings take "
                    "precedence over config.toml",
                    provider.provider_id,
                )
                continue
            await interface.providers.create_provider(provider)

    login_device = _config_login_device(config)
    key_register = (
        SQLiteApiKeyRegister(config.runtime.database_path)
        if login_device is not None
        else None
    )
    key_manager = ApiKeyManager(key_register) if key_register is not None else None
    key_device = (
        ManagedApiKeyHttpAuthDevice(
            ManagedApiKeyAuthDevice(
                key_manager,
                [principal_for_user(user) for user in config.auth.users],
            )
        )
        if key_manager is not None
        else None
    )

    async def close_key_register() -> None:
        if key_register is not None:
            key_register.close()

    return create_http_app(
        interface,
        auth_device=_config_auth_device(config, login_device, key_device),
        login_device=login_device,
        api_key_manager=key_manager,
        workspace_directories=runtime.workspace_directories,
        authorized_interface_factory=_authorized_interface_factory(),
        close_on_shutdown=close_on_shutdown,
        initialize_handler=runtime.initialize,
        readiness_checker=lambda: runtime.is_ready,
        startup_handlers=[register_configured_providers],
        shutdown_handlers=[close_key_register],
        server_header=config.http.server_header,
        static_files_path=config.http.static_files_path,
    )


def _env_auth_device() -> HttpAuthDeviceProtocol | None:
    devices: list[HttpAuthDeviceProtocol] = []
    api_key = os.getenv("EVERNIGHTAI_HTTP_API_KEY")
    if api_key is not None and api_key != "":
        principal = Principal(
            principal_id=os.getenv(
                "EVERNIGHTAI_HTTP_AUTH_PRINCIPAL_ID",
                DEFAULT_HTTP_AUTH_PRINCIPAL_ID,
            ),
            permissions=_env_set("EVERNIGHTAI_HTTP_AUTH_PERMISSIONS") or ["*"],
        )
        devices.append(
            ApiKeyHttpAuthDevice(
                [HttpApiKeyCredential(api_key=api_key, principal=principal)]
            )
        )

    access_token = os.getenv("EVERNIGHTAI_HTTP_OAUTH_ACCESS_TOKEN")
    if access_token is not None and access_token != "":
        principal = Principal(
            principal_id=os.getenv(
                "EVERNIGHTAI_HTTP_OAUTH_PRINCIPAL_ID",
                DEFAULT_HTTP_OAUTH_PRINCIPAL_ID,
            ),
            permissions=_env_set("EVERNIGHTAI_HTTP_OAUTH_PERMISSIONS") or ["*"],
        )
        devices.append(
            OAuthBearerHttpAuthDevice(
                [
                    HttpOAuthBearerCredential(
                        access_token=access_token,
                        principal=principal,
                    )
                ]
            )
        )

    return _combine_auth_devices(devices)


def _config_login_device(
    config: EvernightConfig,
) -> PasswordLoginHttpAuthDevice | None:
    if not config.auth.enabled or not config.auth.users:
        return None

    credentials: list[HttpPasswordCredential] = []
    for user in config.auth.users:
        if user.password is None:
            raise ConfigurationError(
                f"Password for auth user {user.username} is not configured"
            )
        credentials.append(
            HttpPasswordCredential(
                username=user.username,
                password=user.password,
                principal=principal_for_user(user),
            )
        )

    return PasswordLoginHttpAuthDevice(
        credentials,
        session_ttl_seconds=config.auth.login_session_ttl_seconds,
    )


def _config_auth_device(
    config: EvernightConfig,
    login_device: PasswordLoginHttpAuthDevice | None = None,
    key_device: HttpAuthDeviceProtocol | None = None,
) -> HttpAuthDeviceProtocol | None:
    if not config.auth.enabled:
        return None

    devices: list[HttpAuthDeviceProtocol] = []
    if login_device is not None:
        devices.append(login_device)
    if key_device is not None:
        devices.append(key_device)

    oauth_credentials = [
        HttpOAuthBearerCredential(
            access_token=token.access_token,
            principal=Principal(
                principal_id=token.principal_id,
                principal_type=token.principal_type,
                roles=token.roles,
                permissions=token.permissions,
                metadata=token.metadata,
            ),
        )
        for token in config.auth.oauth.tokens
        if token.access_token is not None
    ]
    if oauth_credentials:
        devices.append(OAuthBearerHttpAuthDevice(oauth_credentials))

    oauth_jwt_device = _config_oauth_jwt_auth_device(config)
    if oauth_jwt_device is not None:
        devices.append(oauth_jwt_device)

    if not devices:
        return CompositeHttpAuthDevice([])

    return _combine_auth_devices(devices)


def _config_oauth_jwt_auth_device(
    config: EvernightConfig,
) -> OAuthJwtBearerHttpAuthDevice | None:
    jwt_config = config.auth.oauth.jwt
    if jwt_config is None:
        return None
    if jwt_config.issuer is None:
        raise ConfigurationError("OAuth JWT issuer is required")
    if jwt_config.jwks_url is None:
        raise ConfigurationError("OAuth JWT JWKS URL is required")
    if not jwt_config.audience:
        raise ConfigurationError("OAuth JWT audience is required")
    if not jwt_config.algorithms:
        raise ConfigurationError("OAuth JWT algorithms are required")

    return OAuthJwtBearerHttpAuthDevice(
        HttpOAuthJwtConfig(
            issuer=jwt_config.issuer,
            audience=jwt_config.audience,
            jwks_url=jwt_config.jwks_url,
            algorithms=jwt_config.algorithms,
            leeway_seconds=jwt_config.leeway_seconds,
            principal_id_claim=jwt_config.principal_id_claim,
            principal_type=jwt_config.principal_type,
            roles_claim=jwt_config.roles_claim,
            scope_claim=jwt_config.scope_claim,
            permissions_claim=jwt_config.permissions_claim,
            default_permissions=jwt_config.default_permissions,
            role_permission_map=jwt_config.role_permission_map,
            scope_permission_map=jwt_config.scope_permission_map,
        )
    )


def _combine_auth_devices(
    devices: list[HttpAuthDeviceProtocol],
) -> HttpAuthDeviceProtocol | None:
    if len(devices) == 0:
        return None
    if len(devices) == 1:
        return devices[0]

    return CompositeHttpAuthDevice(devices)


def _authorized_interface_factory():
    authorizer = Authorizer(PermissionAuthPolicy())

    def factory(interface, principal):
        return AuthorizedEvernightInterface(interface, authorizer, principal)

    return factory


def _env_path(name: str, default: str | Path) -> str | Path:
    return os.getenv(name) or default


def _env_optional_string(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    if value == "":
        return None

    return value


def _env_optional_path(name: str) -> str | Path | None:
    value = os.getenv(name)
    if value is None or value == "":
        return None

    return value


def _env_optional_set(name: str) -> set[str] | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None

    return {item.strip() for item in value.split(",") if item.strip()}


def _env_set(name: str) -> list[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return []

    return [item.strip() for item in value.split(",") if item.strip()]


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


def _env_optional_int(name: str, default: int) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    if value.strip().lower() in {"none", "null", "disabled"}:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} must be a nonnegative integer or none"
        ) from exc
    if parsed < 0:
        raise ConfigurationError(f"{name} must be a nonnegative integer or none")
    return parsed


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default

    return float(value)
