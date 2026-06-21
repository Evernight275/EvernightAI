import json
from pathlib import Path
from typing import Any

from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.provider import ProviderConfig
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


def list_providers(config: EvernightConfig) -> str:
    if not config.providers:
        return "No providers declared."

    rows = [
        [
            provider.provider_id,
            provider.name,
            provider.type.value,
            "yes" if provider.is_enabled else "no",
            str(len(provider.model)),
        ]
        for provider in config.providers
    ]
    return _format_table(
        ["PROVIDER ID", "NAME", "TYPE", "ENABLED", "MODELS"],
        rows,
    )


def list_models(config: EvernightConfig, provider_id: str) -> str:
    provider = _find_provider(config, provider_id)
    if provider is None:
        raise ConfigurationError(
            f"Provider '{provider_id}' is not declared in config"
        )

    if not provider.model:
        return f"No models declared for provider '{provider_id}'."

    rows = [
        [
            model.model_id,
            ", ".join(
                capability.value for capability in model.capabilities
            )
            or "-",
        ]
        for model in provider.model.values()
    ]
    return _format_table(["MODEL ID", "CAPABILITIES"], rows)


async def run_chat(
    interface: EvernightInterfaceProtocol,
    config: EvernightConfig,
    *,
    provider_id: str,
    model_id: str,
    prompt: str,
) -> str:
    provider_config = _find_provider(config, provider_id)
    if provider_config is None:
        raise ConfigurationError(
            f"Provider '{provider_id}' is not declared in config"
        )
    if not provider_config.is_enabled:
        raise ConfigurationError(
            f"Provider '{provider_id}' is disabled in config"
        )

    await interface.chat.create_provider(provider_config)
    request = ChatRequest(
        model_id=model_id,
        messages=[
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text=prompt)],
            )
        ],
    )
    response = await interface.chat.chat(provider_id, request)
    return _extract_text(response.message)


def format_config_summary(config: EvernightConfig) -> str:
    enabled_providers = [
        provider
        for provider in config.providers
        if provider.is_enabled
    ]
    lines = [
        "Config OK",
        f"runtime.database_path: {config.runtime.database_path}",
        f"http: {config.http.host}:{config.http.port}",
        f"providers: {len(config.providers)}",
        f"providers.enabled: {len(enabled_providers)}",
        f"tools.filesystem.enabled: {config.tools.filesystem.enabled}",
        f"tools.shell.enabled: {config.tools.shell.enabled}",
        f"tools.shell.allowed_commands: {len(config.tools.shell.allowed_commands)}",
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


def _find_provider(
    config: EvernightConfig,
    provider_id: str,
) -> ProviderConfig | None:
    for provider in config.providers:
        if provider.provider_id == provider_id:
            return provider

    return None


def _extract_text(message: Content) -> str:
    if not message.content:
        return ""

    return "".join(
        part.text or ""
        for part in message.content
        if part.type is ContentPartType.TEXT
    )


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = {
        header: max(
            len(header),
            *(len(row[index]) for row in rows),
        )
        for index, header in enumerate(headers)
    }
    header_line = "  ".join(header.ljust(widths[header]) for header in headers)
    body_lines = [
        "  ".join(
            row[index].ljust(widths[header])
            for index, header in enumerate(headers)
        )
        for row in rows
    ]
    return "\n".join([header_line, *body_lines])
