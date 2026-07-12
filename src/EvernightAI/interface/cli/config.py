import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, ValidationError as PydanticValidationError

from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.schema.data_analysis import (
    DataFieldDefinition,
    DataMetricDefinition,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelConfig,
)
from EvernightAI.interface.cli.schema import (
    AuthConfig,
    AuthPrincipalConfig,
    ContextStrategyConfig,
    DataAnalysisConfig,
    EvernightConfig,
    HttpConfig,
    OAuthConfig,
    OAuthJwtConfig,
    OAuthTokenPrincipalConfig,
    RuntimeConfig,
    SQLiteDataSourceConfig,
    ToolConfig,
)


class _ProviderModelConfigInput(ProviderModelConfig):
    model_config = ConfigDict(extra="forbid")


def load_config(path: str | Path) -> EvernightConfig:
    try:
        data = _read_toml(path)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError("Invalid TOML config", detail=str(exc)) from exc
    except OSError as exc:
        raise ConfigurationError(f"Could not read config file: {path}") from exc

    return parse_config(data)


def parse_config(data: dict[str, Any]) -> EvernightConfig:
    try:
        return EvernightConfig(
            runtime=RuntimeConfig.model_validate(data.get("runtime", {})),
            context_strategy=ContextStrategyConfig.model_validate(
                data.get("context_strategy", {})
            ),
            http=HttpConfig.model_validate(data.get("http", {})),
            tools=ToolConfig.model_validate(data.get("tools", {})),
            auth=_parse_auth(data.get("auth", {})),
            data_analysis=_parse_data_analysis(data.get("data_analysis", {})),
            providers=_parse_providers(data.get("provider", {})),
        )
    except (KeyError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ConfigurationError("Invalid EvernightAI config", detail=str(exc)) from exc


def _read_toml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("rb") as file:
        data = tomllib.load(file)

    return data


def _parse_providers(raw: object) -> list[ProviderConfig]:
    if not isinstance(raw, dict):
        return []

    return [
        _parse_provider(provider_key, provider_data)
        for provider_key, provider_data in raw.items()
        if isinstance(provider_key, str) and isinstance(provider_data, dict)
    ]


def _parse_auth(raw: object) -> AuthConfig:
    if not isinstance(raw, dict):
        return AuthConfig()

    return AuthConfig(
        enabled=_bool(raw.get("enabled"), False),
        principals=_parse_auth_principals(raw.get("principal", {})),
        oauth=_parse_oauth(raw.get("oauth", {})),
    )


def _parse_data_analysis(raw: object) -> DataAnalysisConfig:
    if not isinstance(raw, dict):
        return DataAnalysisConfig()

    return DataAnalysisConfig(
        sqlite_sources=_parse_sqlite_data_sources(raw.get("sqlite_source", {}))
    )


def _parse_sqlite_data_sources(raw: object) -> list[SQLiteDataSourceConfig]:
    if not isinstance(raw, dict):
        return []

    return [
        _parse_sqlite_data_source(source_key, source_data)
        for source_key, source_data in raw.items()
        if isinstance(source_key, str) and isinstance(source_data, dict)
    ]


def _parse_sqlite_data_source(
    source_key: str,
    data: dict[str, Any],
) -> SQLiteDataSourceConfig:
    source_id = _string(data.get("source_id")) or source_key
    table = _string(data.get("table")) or source_id
    return SQLiteDataSourceConfig(
        source_id=source_id,
        name=_string(data.get("name")) or source_id,
        table=table,
        description=_string(data.get("description")),
        fields=_parse_data_fields(data.get("field", {})),
        metrics=_parse_data_metrics(data.get("metric", {})),
        metadata={
            **_dict(data.get("metadata")),
            "sqlite_table": table,
        },
    )


def _parse_data_fields(raw: object) -> list[DataFieldDefinition]:
    if not isinstance(raw, dict):
        return []

    return [
        DataFieldDefinition.model_validate(
            {
                **field_data,
                "field_id": _string(field_data.get("field_id")) or field_key,
                "name": _string(field_data.get("name")) or field_key,
            }
        )
        for field_key, field_data in raw.items()
        if isinstance(field_key, str) and isinstance(field_data, dict)
    ]


def _parse_data_metrics(raw: object) -> list[DataMetricDefinition]:
    if not isinstance(raw, dict):
        return []

    return [
        DataMetricDefinition.model_validate(
            {
                **metric_data,
                "metric_id": _string(metric_data.get("metric_id")) or metric_key,
                "name": _string(metric_data.get("name")) or metric_key,
            }
        )
        for metric_key, metric_data in raw.items()
        if isinstance(metric_key, str) and isinstance(metric_data, dict)
    ]


def _parse_auth_principals(raw: object) -> list[AuthPrincipalConfig]:
    if not isinstance(raw, dict):
        return []

    return [
        _parse_auth_principal(principal_key, principal_data)
        for principal_key, principal_data in raw.items()
        if isinstance(principal_key, str) and isinstance(principal_data, dict)
    ]


def _parse_auth_principal(
    principal_key: str,
    data: dict[str, Any],
) -> AuthPrincipalConfig:
    return AuthPrincipalConfig(
        principal_id=_string(data.get("principal_id")) or principal_key,
        principal_type=data.get("principal_type", "user"),
        api_key=_api_key(data),
        roles=_string_list(data.get("roles")),
        permissions=_string_list(data.get("permissions")),
        metadata=_dict(data.get("metadata")),
    )


def _parse_oauth(raw: object) -> OAuthConfig:
    if not isinstance(raw, dict):
        return OAuthConfig()

    return OAuthConfig(
        tokens=_parse_oauth_tokens(raw.get("token", {})),
        jwt=_parse_oauth_jwt(raw.get("jwt")),
    )


def _parse_oauth_tokens(raw: object) -> list[OAuthTokenPrincipalConfig]:
    if not isinstance(raw, dict):
        return []

    return [
        _parse_oauth_token(token_key, token_data)
        for token_key, token_data in raw.items()
        if isinstance(token_key, str) and isinstance(token_data, dict)
    ]


def _parse_oauth_token(
    token_key: str,
    data: dict[str, Any],
) -> OAuthTokenPrincipalConfig:
    return OAuthTokenPrincipalConfig(
        principal_id=_string(data.get("principal_id")) or token_key,
        principal_type=data.get("principal_type", "user"),
        access_token=_access_token(data),
        roles=_string_list(data.get("roles")),
        permissions=_string_list(data.get("permissions")),
        metadata=_dict(data.get("metadata")),
    )


def _parse_oauth_jwt(raw: object) -> OAuthJwtConfig | None:
    if not isinstance(raw, dict):
        return None

    return OAuthJwtConfig(
        issuer=_string(raw.get("issuer")),
        audience=_string_or_string_list(raw.get("audience")),
        jwks_url=_string(raw.get("jwks_url")),
        algorithms=_string_list(raw.get("algorithms")) or ["RS256"],
        leeway_seconds=_int(raw.get("leeway_seconds"), 60),
        principal_id_claim=_string(raw.get("principal_id_claim")) or "sub",
        principal_type=raw.get("principal_type", "user"),
        roles_claim=_string(raw.get("roles_claim")) or "roles",
        scope_claim=_string(raw.get("scope_claim")) or "scope",
        permissions_claim=_string(raw.get("permissions_claim")) or "permissions",
        default_permissions=_string_list(raw.get("default_permissions")),
        role_permission_map=_string_list_dict(raw.get("role_permission_map")),
        scope_permission_map=_string_list_dict(raw.get("scope_permission_map")),
    )


def _parse_provider(
    provider_key: str,
    data: dict[str, Any],
) -> ProviderConfig:
    provider_id = _string(data.get("provider_id")) or provider_key
    model_data = data.get("model", {})
    return ProviderConfig(
        provider_id=provider_id,
        name=_string(data.get("name")) or provider_id,
        type=data["type"],
        is_enabled=_bool(data.get("is_enabled"), True),
        discover_models=_bool(data.get("discover_models"), False),
        api_key=_api_key(data),
        base_url=_string(data.get("base_url")),
        model=_parse_models(model_data),
        metadata=_dict(data.get("metadata")),
    )


def _parse_models(raw: object) -> dict[str, ProviderModelConfig]:
    if not isinstance(raw, dict):
        return {}

    models: dict[str, ProviderModelConfig] = {}
    for model_key, model_data in raw.items():
        if not isinstance(model_key, str) or not isinstance(model_data, dict):
            continue

        model_id = _string(model_data.get("model_id")) or model_key
        models[model_id] = _ProviderModelConfigInput.model_validate(
            {
                **model_data,
                "model_id": model_id,
            }
        )

    return models


def _api_key(data: dict[str, Any]) -> str | None:
    api_key = _string(data.get("api_key"))
    if api_key is not None:
        return api_key

    api_key_env = _string(data.get("api_key_env"))
    if api_key_env is None:
        return None

    value = os.getenv(api_key_env)
    if value == "":
        return None

    return value


def _access_token(data: dict[str, Any]) -> str | None:
    access_token = _string(data.get("access_token"))
    if access_token is not None:
        return access_token

    access_token_env = _string(data.get("access_token_env"))
    if access_token_env is None:
        return None

    value = os.getenv(access_token_env)
    if value == "":
        return None

    return value


def _string(value: object) -> str | None:
    if isinstance(value, str) and value != "":
        return value

    return None


def _bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value

    return default


def _int(value: object, default: int) -> int:
    if isinstance(value, int):
        return value

    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


def _string_or_string_list(value: object) -> list[str]:
    if isinstance(value, str) and value != "":
        return [value]

    return _string_list(value)


def _string_list_dict(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}

    return {
        key: _string_or_string_list(item)
        for key, item in value.items()
        if isinstance(key, str)
    }


def _dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str)
    }
