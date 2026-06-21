import os
import tomllib
from pathlib import Path
from typing import Any

from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelConfig,
)
from EvernightAI.interface.cli.schema import (
    EvernightConfig,
    HttpConfig,
    RuntimeConfig,
    ToolConfig,
)


def load_config(path: str | Path) -> EvernightConfig:
    return parse_config(_read_toml(path))


def parse_config(data: dict[str, Any]) -> EvernightConfig:
    return EvernightConfig(
        runtime=RuntimeConfig.model_validate(data.get("runtime", {})),
        http=HttpConfig.model_validate(data.get("http", {})),
        tools=ToolConfig.model_validate(data.get("tools", {})),
        providers=_parse_providers(data.get("provider", {})),
    )


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
        models[model_id] = ProviderModelConfig.model_validate(
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


def _string(value: object) -> str | None:
    if isinstance(value, str) and value != "":
        return value

    return None


def _bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value

    return default


def _dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str)
    }
