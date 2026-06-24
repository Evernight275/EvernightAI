import pytest

from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.interface.cli.auth import ConfigCliAuthDevice
from EvernightAI.interface.cli.config import parse_config


def test_cli_auth_device_uses_single_configured_principal_without_env_key() -> None:
    config = parse_config(
        {
            "auth": {
                "enabled": True,
                "principal": {
                    "admin": {
                        "api_key": "secret",
                        "permissions": ["*"],
                    }
                },
            }
        }
    )

    principal = ConfigCliAuthDevice().principal_for_config(config)

    assert principal.principal_id == "admin"
    assert principal.permissions == ["*"]


def test_cli_auth_device_uses_env_key_to_select_principal(monkeypatch) -> None:
    monkeypatch.setenv("EVERNIGHTAI_CLI_API_KEY", "writer-secret")
    config = parse_config(
        {
            "auth": {
                "enabled": True,
                "principal": {
                    "reader": {
                        "api_key": "reader-secret",
                        "permissions": ["contexts:list"],
                    },
                    "writer": {
                        "api_key": "writer-secret",
                        "permissions": ["contexts:create"],
                    },
                },
            }
        }
    )

    principal = ConfigCliAuthDevice().principal_for_config(config)

    assert principal.principal_id == "writer"
    assert principal.permissions == ["contexts:create"]


def test_cli_auth_device_rejects_missing_key_for_multiple_principals() -> None:
    config = parse_config(
        {
            "auth": {
                "enabled": True,
                "principal": {
                    "reader": {"api_key": "reader-secret"},
                    "writer": {"api_key": "writer-secret"},
                },
            }
        }
    )

    with pytest.raises(AuthRequiredError):
        ConfigCliAuthDevice().principal_for_config(config)


def test_cli_auth_device_rejects_invalid_env_key(monkeypatch) -> None:
    monkeypatch.setenv("EVERNIGHTAI_CLI_API_KEY", "wrong")
    config = parse_config(
        {
            "auth": {
                "enabled": True,
                "principal": {
                    "reader": {"api_key": "reader-secret"},
                },
            }
        }
    )

    with pytest.raises(AuthRequiredError):
        ConfigCliAuthDevice().principal_for_config(config)
