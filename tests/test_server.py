import pytest
from fastapi.testclient import TestClient

from EvernightAI.bootstrap.http import create_app as create_http_app
from EvernightAI.bootstrap.http import create_app_from_config
from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.interface.cli.schema import (
    AuthConfig,
    AuthPrincipalConfig,
    EvernightConfig,
    HttpConfig,
    OAuthConfig,
    OAuthJwtConfig,
    OAuthTokenPrincipalConfig,
    RuntimeConfig,
)
from EvernightAI.entrypoint.server import _startup_info_lines
from EvernightAI.server import main as package_server_main


@pytest.fixture(autouse=True)
def isolate_http_bootstrap_env(monkeypatch) -> None:
    env_names = [
        "EVERNIGHTAI_DATABASE_PATH",
        "EVERNIGHTAI_FILESYSTEM_ROOT",
        "EVERNIGHTAI_ALLOW_FILE_OVERWRITE",
        "EVERNIGHTAI_SHELL_ALLOWED_COMMANDS",
        "EVERNIGHTAI_SHELL_WORKING_DIRECTORY",
        "EVERNIGHTAI_SHELL_TIMEOUT_SECONDS",
        "EVERNIGHTAI_SHELL_MAX_OUTPUT_CHARS",
        "EVERNIGHTAI_HTTP_API_KEY",
        "EVERNIGHTAI_HTTP_AUTH_PRINCIPAL_ID",
        "EVERNIGHTAI_HTTP_AUTH_PERMISSIONS",
        "EVERNIGHTAI_HTTP_OAUTH_ACCESS_TOKEN",
        "EVERNIGHTAI_HTTP_OAUTH_PRINCIPAL_ID",
        "EVERNIGHTAI_HTTP_OAUTH_PERMISSIONS",
        "EVERNIGHTAI_HTTP_SERVER_HEADER",
        "EVERNIGHTAI_HTTP_STATIC_FILES_PATH",
    ]
    for name in env_names:
        monkeypatch.delenv(name, raising=False)


def test_http_bootstrap_factory_creates_http_app(tmp_path) -> None:
    app = create_http_app(
        database_path=tmp_path / "entrypoint.sqlite3",
        filesystem_root=tmp_path,
        close_on_shutdown=False,
    )

    assert_http_app(app)


def test_http_bootstrap_can_enable_env_api_key_auth(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EVERNIGHTAI_HTTP_API_KEY", "secret")
    monkeypatch.setenv("EVERNIGHTAI_HTTP_AUTH_PERMISSIONS", "tools:list")

    app = create_http_app(
        database_path=tmp_path / "entrypoint.sqlite3",
        filesystem_root=tmp_path,
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        missing_response = client.get("/tools")
        valid_response = client.get(
            "/tools",
            headers={"authorization": "Bearer secret"},
        )

    assert missing_response.status_code == 401
    assert valid_response.status_code == 200


def test_http_bootstrap_can_enable_env_oauth_bearer_auth(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("EVERNIGHTAI_HTTP_OAUTH_ACCESS_TOKEN", "oauth-token")
    monkeypatch.setenv("EVERNIGHTAI_HTTP_OAUTH_PERMISSIONS", "tools:list")

    app = create_http_app(
        database_path=tmp_path / "entrypoint.sqlite3",
        filesystem_root=tmp_path,
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        missing_response = client.get("/tools")
        valid_response = client.get(
            "/tools",
            headers={"authorization": "Bearer oauth-token"},
        )

    assert missing_response.status_code == 401
    assert valid_response.status_code == 200


def test_http_bootstrap_can_enable_config_api_key_auth(tmp_path) -> None:
    app = create_app_from_config(
        EvernightConfig(
            runtime=RuntimeConfig(
                database_path=(tmp_path / "runtime.sqlite3").as_posix()
            ),
            auth=AuthConfig(
                enabled=True,
                principals=[
                    AuthPrincipalConfig(
                        principal_id="admin",
                        api_key="secret",
                        permissions=["tools:list"],
                    )
                ],
            ),
        ),
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        missing_response = client.get("/tools")
        valid_response = client.get(
            "/tools",
            headers={"x-evernight-api-key": "secret"},
        )

    assert missing_response.status_code == 401
    assert valid_response.status_code == 200


def test_http_bootstrap_can_set_custom_server_header(tmp_path) -> None:
    app = create_app_from_config(
        EvernightConfig(
            runtime=RuntimeConfig(
                database_path=(tmp_path / "runtime.sqlite3").as_posix()
            ),
            http=HttpConfig(server_header="EvernightAdmin"),
        ),
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.headers["server"] == "EvernightAdmin"


def test_http_bootstrap_can_serve_configured_static_frontend(tmp_path) -> None:
    static_path = tmp_path / "frontend-dist"
    static_path.mkdir()
    (static_path / "index.html").write_text(
        "<!doctype html><title>Frontend</title>",
        encoding="utf-8",
    )
    app = create_app_from_config(
        EvernightConfig(
            runtime=RuntimeConfig(
                database_path=(tmp_path / "runtime.sqlite3").as_posix()
            ),
            http=HttpConfig(static_files_path=static_path.as_posix()),
        ),
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Frontend" in response.text


def test_http_bootstrap_can_serve_env_static_frontend(tmp_path, monkeypatch) -> None:
    static_path = tmp_path / "env-frontend-dist"
    static_path.mkdir()
    (static_path / "index.html").write_text(
        "<!doctype html><title>Env Frontend</title>",
        encoding="utf-8",
    )
    monkeypatch.setenv("EVERNIGHTAI_HTTP_STATIC_FILES_PATH", static_path.as_posix())

    app = create_http_app(
        database_path=tmp_path / "entrypoint.sqlite3",
        filesystem_root=tmp_path,
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Env Frontend" in response.text


def test_http_bootstrap_can_enable_config_oauth_bearer_auth(tmp_path) -> None:
    app = create_app_from_config(
        EvernightConfig(
            runtime=RuntimeConfig(
                database_path=(tmp_path / "runtime.sqlite3").as_posix()
            ),
            auth=AuthConfig(
                enabled=True,
                oauth=OAuthConfig(
                    tokens=[
                        OAuthTokenPrincipalConfig(
                            principal_id="reader",
                            access_token="oauth-token",
                            permissions=["tools:list"],
                        )
                    ],
                ),
            ),
        ),
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        missing_response = client.get("/tools")
        valid_response = client.get(
            "/tools",
            headers={"authorization": "Bearer oauth-token"},
        )

    assert missing_response.status_code == 401
    assert valid_response.status_code == 200


def test_http_bootstrap_can_enable_config_oauth_jwt_auth(tmp_path) -> None:
    app = create_app_from_config(
        EvernightConfig(
            runtime=RuntimeConfig(
                database_path=(tmp_path / "runtime.sqlite3").as_posix()
            ),
            auth=AuthConfig(
                enabled=True,
                oauth=OAuthConfig(
                    jwt=OAuthJwtConfig(
                        issuer="https://idp.example.test",
                        audience=["evernight-admin-api"],
                        jwks_url="https://idp.example.test/.well-known/jwks.json",
                        algorithms=["RS256"],
                        role_permission_map={"evernight-admin": ["*"]},
                    )
                ),
            ),
        ),
        close_on_shutdown=False,
    )

    assert app.state.auth_device is not None


def test_http_bootstrap_rejects_incomplete_oauth_jwt_config(tmp_path) -> None:
    try:
        create_app_from_config(
            EvernightConfig(
                runtime=RuntimeConfig(
                    database_path=(tmp_path / "runtime.sqlite3").as_posix()
                ),
                auth=AuthConfig(
                    enabled=True,
                    oauth=OAuthConfig(
                        jwt=OAuthJwtConfig(
                            issuer="https://idp.example.test",
                            audience=["evernight-admin-api"],
                        )
                    ),
                ),
            ),
            close_on_shutdown=False,
        )
    except ConfigurationError as exc:
        assert "JWKS URL" in str(exc)
    else:
        raise AssertionError("Expected ConfigurationError")


def test_http_bootstrap_keeps_auth_enabled_without_credentials(tmp_path) -> None:
    app = create_app_from_config(
        EvernightConfig(
            runtime=RuntimeConfig(
                database_path=(tmp_path / "runtime.sqlite3").as_posix()
            ),
            auth=AuthConfig(enabled=True),
        ),
        close_on_shutdown=False,
    )

    auth_device = app.state.auth_device
    assert auth_device is not None
    try:
        auth_device.principal(None)
    except AuthRequiredError:
        pass
    else:
        raise AssertionError("Expected AuthRequiredError")


def test_package_server_wrapper_exposes_main() -> None:
    assert package_server_main is not None


def test_server_startup_info_skips_terminal_control_codes_without_color() -> None:
    lines = _startup_info_lines(
        "config.toml",
        host="127.0.0.1",
        port=9001,
        static_files_path="frontend/dist",
        auth_enabled=True,
        color=False,
    )
    output = "\n".join(lines)

    assert "\033[2J\033[H" not in output
    assert "http://127.0.0.1:9001/docs" in output
    assert "ws://127.0.0.1:9001/ws" in output
    assert "Auth：" in output
    assert "enabled" in output
    assert "Static：" in output
    assert "frontend/dist" in output


def test_server_startup_info_clears_terminal_when_color_is_enabled() -> None:
    lines = _startup_info_lines(
        "config.toml",
        host="127.0.0.1",
        port=8000,
        color=True,
    )

    assert lines[0] == "\033[2J\033[H"
    assert "\033[" in lines[1]


def test_package_server_starts_from_config(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    app = object()
    calls = {}
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[runtime]
database_path = "{(tmp_path / "runtime.sqlite3").as_posix()}"

[http]
host = "0.0.0.0"
port = 8123
reload = true
""".strip(),
        encoding="utf-8",
    )

    def create_app_from_config(config):
        calls["database_path"] = config.runtime.database_path
        return app

    def run(started_app, *, host, port, reload, log_config, server_header):
        calls["app"] = started_app
        calls["host"] = host
        calls["port"] = port
        calls["reload"] = reload
        calls["log_config"] = log_config
        calls["server_header"] = server_header

    monkeypatch.setattr(
        "EvernightAI.entrypoint.server.create_app_from_config",
        create_app_from_config,
    )
    monkeypatch.setattr("EvernightAI.entrypoint.server.uvicorn.run", run)

    exit_code = package_server_main(["--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert calls["database_path"] == (tmp_path / "runtime.sqlite3").as_posix()
    assert calls["app"] is app
    assert calls["host"] == "0.0.0.0"
    assert calls["port"] == 8123
    assert calls["reload"] is True
    assert calls["server_header"] is False
    assert calls["log_config"]["formatters"]["evernight"] == {
        "()": "EvernightAI.interface.cli.logging.EvernightLogFormatter",
    }


def assert_http_app(app) -> None:
    with TestClient(app) as client:
        health_response = client.get("/health")
        tools_response = client.get("/tools")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert [tool["name"] for tool in tools_response.json()] == [
        "read_text_file",
        "write_text_file",
        "append_text_file",
        "list_directory",
        "find_paths",
        "search_text_files",
        "read_text_file_lines",
        "move_path",
        "delete_path",
        "apply_text_patch",
        "file_hash",
        "path_info",
        "make_directory",
        "copy_path",
        "read_json_file",
        "write_json_file",
    ]
