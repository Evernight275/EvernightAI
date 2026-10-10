import pytest

from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.interface.cli.auth import ConfigCliAuthDevice
from EvernightAI.interface.cli.config import parse_config


def test_cli_auth_device_uses_single_configured_local_user() -> None:
    config = parse_config(
        {
            "auth": {
                "enabled": True,
                "user": {
                    "admin": {
                        "password": "secret",
                        "permissions": ["*"],
                    }
                },
            }
        }
    )

    principal = ConfigCliAuthDevice().principal_for_config(config)

    assert principal.principal_id == "admin"
    assert principal.permissions == ["*"]


def test_cli_auth_device_uses_login_to_select_user(monkeypatch) -> None:
    monkeypatch.setenv("EVERNIGHTAI_CLI_USERNAME", "writer")
    monkeypatch.setenv("EVERNIGHTAI_CLI_PASSWORD", "writer-secret")
    config = parse_config(
        {
            "auth": {
                "enabled": True,
                "user": {
                    "reader": {
                        "password": "reader-secret",
                        "permissions": ["contexts:list"],
                    },
                    "writer": {
                        "password": "writer-secret",
                        "permissions": ["contexts:create"],
                    },
                },
            }
        }
    )

    principal = ConfigCliAuthDevice().principal_for_config(config)

    assert principal.principal_id == "writer"
    assert principal.permissions == ["contexts:create"]


def test_cli_auth_device_requires_login_for_multiple_users() -> None:
    config = parse_config(
        {
            "auth": {
                "enabled": True,
                "user": {
                    "reader": {"password": "reader-secret"},
                    "writer": {"password": "writer-secret"},
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
                "user": {
                    "reader": {"password": "reader-secret"},
                },
            }
        }
    )

    with pytest.raises(AuthRequiredError):
        ConfigCliAuthDevice().principal_for_config(config)


@pytest.mark.parametrize("password", [None, "wrong"])
def test_cli_rejects_invalid_password(monkeypatch, password: str | None) -> None:
    monkeypatch.setenv("EVERNIGHTAI_CLI_USERNAME", "reader")
    if password is None:
        monkeypatch.delenv("EVERNIGHTAI_CLI_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("EVERNIGHTAI_CLI_PASSWORD", password)
    config = parse_config(
        {"auth": {"enabled": True, "user": {"reader": {"password": "correct"}}}}
    )
    with pytest.raises(AuthRequiredError):
        ConfigCliAuthDevice().principal_for_config(config)


@pytest.mark.parametrize("use_env", [False, True])
def test_cli_rejects_legacy_config_keys(monkeypatch, use_env: bool) -> None:
    monkeypatch.setenv("EVERNIGHTAI_CLI_API_KEY", "legacy-secret")
    monkeypatch.setenv("LEGACY_AUTH_KEY", "legacy-secret")
    entry = (
        {"api_key_env": "LEGACY_AUTH_KEY"} if use_env else {"api_key": "legacy-secret"}
    )
    config = parse_config({"auth": {"enabled": True, "principal": {"reader": entry}}})
    with pytest.raises(AuthRequiredError):
        ConfigCliAuthDevice().principal_for_config(config)
