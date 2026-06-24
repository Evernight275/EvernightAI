from pathlib import Path

from EvernightAI.core.schema.provider import (
    ProviderModelCapability,
    ProviderType,
)
from EvernightAI.interface.cli.config import load_config, parse_config


def test_parse_config_maps_toml_shape_to_core_provider_config(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")

    config = parse_config(
        {
            "runtime": {
                "database_path": ".evernight/test.sqlite3",
            },
            "http": {
                "host": "0.0.0.0",
                "port": 8080,
                "reload": True,
            },
            "tools": {
                "filesystem": {
                    "enabled": True,
                    "root": ".",
                    "max_read_chars": 8000,
                    "allow_write": True,
                },
                "shell": {
                    "enabled": True,
                    "allowed_commands": ["python", "pytest"],
                    "timeout_seconds": 3.5,
                },
            },
            "provider": {
                "main": {
                    "name": "DeepSeek",
                    "type": "openai",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "base_url": "https://example.test/v1",
                    "metadata": {"source": "test"},
                    "model": {
                        "deepseek-chat": {
                            "capabilities": ["chat", "tool_call"],
                        }
                    },
                }
            },
        }
    )

    provider = config.providers[0]
    model = provider.model["deepseek-chat"]

    assert config.runtime.database_path == ".evernight/test.sqlite3"
    assert config.http.host == "0.0.0.0"
    assert config.http.port == 8080
    assert config.http.reload is True
    assert config.tools.filesystem.enabled is True
    assert config.tools.filesystem.root == "."
    assert config.tools.filesystem.max_read_chars == 8000
    assert config.tools.filesystem.allow_write is True
    assert config.tools.shell.enabled is True
    assert config.tools.shell.allowed_commands == ["python", "pytest"]
    assert config.tools.shell.timeout_seconds == 3.5
    assert provider.provider_id == "main"
    assert provider.name == "DeepSeek"
    assert provider.type is ProviderType.OPENAI
    assert provider.api_key == "secret-key"
    assert provider.base_url == "https://example.test/v1"
    assert provider.metadata == {"source": "test"}
    assert model.model_id == "deepseek-chat"
    assert model.capabilities == [
        ProviderModelCapability.CHAT,
        ProviderModelCapability.TOOL_CALL,
    ]


def test_load_config_reads_toml_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[runtime]
database_path = ".evernight/runtime.sqlite3"

[provider.main]
name = "Local"
type = "openai"
api_key = "inline-key"

[provider.main.model.model_1]
model_id = "model-1"
capabilities = ["chat"]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.runtime.database_path == ".evernight/runtime.sqlite3"
    assert config.providers[0].provider_id == "main"
    assert config.providers[0].api_key == "inline-key"
    assert list(config.providers[0].model) == ["model-1"]


def test_parse_config_uses_defaults_for_missing_sections() -> None:
    config = parse_config({})

    assert config.runtime.database_path == ".evernight/runtime.sqlite3"
    assert config.http.host == "127.0.0.1"
    assert config.http.port == 8000
    assert config.tools.filesystem.enabled is False
    assert config.tools.shell.allowed_commands == []
    assert config.providers == []
