from EvernightAI.interface.cli.commands import (
    format_config_summary,
    redact_config,
)
from EvernightAI.interface.cli.config import parse_config


def test_format_config_summary_reports_runtime_and_provider_counts() -> None:
    config = parse_config(
        {
            "runtime": {"database_path": ".evernight/test.sqlite3"},
            "http": {"host": "127.0.0.1", "port": 8010},
            "tools": {
                "filesystem": {"enabled": True, "root": "."},
                "shell": {"enabled": True, "allowed_commands": ["python"]},
            },
            "provider": {
                "main": {"name": "Main", "type": "openai"},
                "off": {
                    "name": "Off",
                    "type": "anthropic",
                    "is_enabled": False,
                },
            },
        }
    )

    assert format_config_summary(config) == "\n".join(
        [
            "Config OK",
            "runtime.database_path: .evernight/test.sqlite3",
            "http: 127.0.0.1:8010",
            "providers: 2",
            "providers.enabled: 1",
            "tools.filesystem.enabled: True",
            "tools.shell.enabled: True",
            "tools.shell.allowed_commands: 1",
            "tools.shell.blocked_commands: 0",
            "tools.mcp.servers: 0",
            "tools.mcp.servers.enabled: 0",
        ]
    )


def test_redact_config_hides_provider_api_keys() -> None:
    config = parse_config(
        {
            "provider": {
                "main": {
                    "name": "Main",
                    "type": "openai",
                    "api_key": "secret-key",
                }
            }
        }
    )

    payload = redact_config(config)

    assert payload["providers"][0]["api_key"] == "***"
