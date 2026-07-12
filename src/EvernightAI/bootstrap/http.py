import os
from pathlib import Path

from fastapi import FastAPI

from EvernightAI.bootstrap.config import create_unsecured_interface_from_config
from EvernightAI.bootstrap.interface import create_authorized_interface, create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.interface.cli.schema import EvernightConfig
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import (
    ApiKeyHttpAuthDevice,
    CompositeHttpAuthDevice,
    HttpApiKeyCredential,
    HttpOAuthJwtConfig,
    HttpOAuthBearerCredential,
    OAuthJwtBearerHttpAuthDevice,
    OAuthBearerHttpAuthDevice,
)
from EvernightAI.interface.http.protocol import HttpAuthDeviceProtocol


DEFAULT_DATABASE_PATH = Path(".evernight") / "runtime.sqlite3"
DEFAULT_HTTP_AUTH_PRINCIPAL_ID = "http-api-key"
DEFAULT_HTTP_OAUTH_PRINCIPAL_ID = "http-oauth"


def create_app(
    *,
    database_path: str | Path | None = None,
    filesystem_root: str | Path | None = None,
    static_files_path: str | Path | None = None,
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
        shell_requires_approval=_env_bool(
            "EVERNIGHTAI_SHELL_IS_NEED_APPROVAL",
            True,
        ),
        trace_retention_days=_env_int(
            "EVERNIGHTAI_TRACE_RETENTION_DAYS",
            30,
        ),
        trace_max_events=_env_int(
            "EVERNIGHTAI_TRACE_MAX_EVENTS",
            100_000,
        ),
    )
    return create_http_app(
        create_interface(runtime),
        auth_device=_env_auth_device(),
        authorized_interface_factory=_authorized_interface_factory(),
        close_on_shutdown=close_on_shutdown,
        initialize_handler=runtime.initialize,
        readiness_checker=lambda: runtime.is_ready,
        server_header=_env_optional_string(
            "EVERNIGHTAI_HTTP_SERVER_HEADER",
            "EvernightAI",
        ),
        static_files_path=static_files_path or _env_optional_path(
            "EVERNIGHTAI_HTTP_STATIC_FILES_PATH"
        ),
    )


def create_app_from_config(
    config: EvernightConfig,
    *,
    close_on_shutdown: bool = True,
) -> FastAPI:
    interface = create_unsecured_interface_from_config(config)
    runtime = interface.runtime

    async def register_configured_providers() -> None:
        for provider in config.providers:
            if provider.is_enabled:
                await interface.providers.create_provider(provider)

    return create_http_app(
        interface,
        auth_device=_config_auth_device(config),
        authorized_interface_factory=_authorized_interface_factory(),
        close_on_shutdown=close_on_shutdown,
        initialize_handler=runtime.initialize,
        readiness_checker=lambda: runtime.is_ready,
        startup_handlers=[register_configured_providers],
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
            _api_key_auth_device(
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
            _oauth_bearer_auth_device(
                [
                    HttpOAuthBearerCredential(
                        access_token=access_token,
                        principal=principal,
                    )
                ]
            )
        )

    return _combine_auth_devices(devices)


def _config_auth_device(config: EvernightConfig) -> HttpAuthDeviceProtocol | None:
    if not config.auth.enabled:
        return None

    devices: list[HttpAuthDeviceProtocol] = []
    api_key_credentials = [
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
    if api_key_credentials:
        devices.append(_api_key_auth_device(api_key_credentials))

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
        devices.append(_oauth_bearer_auth_device(oauth_credentials))

    oauth_jwt_device = _config_oauth_jwt_auth_device(config)
    if oauth_jwt_device is not None:
        devices.append(oauth_jwt_device)

    if not devices:
        return CompositeHttpAuthDevice([])

    return _combine_auth_devices(devices)


def _api_key_auth_device(
    credentials: list[HttpApiKeyCredential],
) -> ApiKeyHttpAuthDevice:
    return ApiKeyHttpAuthDevice(credentials)


def _oauth_bearer_auth_device(
    credentials: list[HttpOAuthBearerCredential],
) -> OAuthBearerHttpAuthDevice:
    return OAuthBearerHttpAuthDevice(credentials)


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
        return create_authorized_interface(interface, authorizer, principal)

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
