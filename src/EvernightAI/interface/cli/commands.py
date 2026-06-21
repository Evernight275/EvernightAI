import json
from pathlib import Path
from typing import Any

from EvernightAI.interface.cli.config import load_config
from EvernightAI.interface.cli.schema import EvernightConfig


def check_config(path: str | Path) -> str:
    config = load_config(path)
    return format_config_summary(config)


def show_config(path: str | Path) -> str:
    config = load_config(path)
    return json.dumps(
        redact_config(config),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def format_config_summary(config: EvernightConfig) -> str:
    enabled_providers = [
        provider
        for provider in config.providers
        if provider.is_enabled
    ]
    lines = [
        "Config OK",
        f"runtime.database_path: {config.runtime.database_path}",
        f"runtime.filesystem_root: {config.runtime.filesystem_root or ''}",
        f"http: {config.http.host}:{config.http.port}",
        f"providers: {len(config.providers)}",
        f"providers.enabled: {len(enabled_providers)}",
        f"tools.shell_allowed_commands: {len(config.tools.shell_allowed_commands)}",
    ]

    return "\n".join(lines)


def redact_config(config: EvernightConfig) -> dict[str, Any]:
    payload = config.model_dump(mode="json")
    providers = payload.get("providers")
    if isinstance(providers, list):
        for provider in providers:
            if isinstance(provider, dict) and provider.get("api_key"):
                provider["api_key"] = "***"

    return payload
