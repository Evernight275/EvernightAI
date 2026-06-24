from fastapi.testclient import TestClient

from EvernightAI.bootstrap.http import create_app as create_http_app
from EvernightAI.server import main as package_server_main


def test_http_bootstrap_factory_creates_http_app(tmp_path) -> None:
    app = create_http_app(
        database_path=tmp_path / "entrypoint.sqlite3",
        filesystem_root=tmp_path,
        close_on_shutdown=False,
    )

    assert_http_app(app)


def test_package_server_wrapper_exposes_main() -> None:
    assert package_server_main is not None


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

    def run(started_app, *, host, port, reload):
        calls["app"] = started_app
        calls["host"] = host
        calls["port"] = port
        calls["reload"] = reload

    monkeypatch.setattr(
        "EvernightAI.entrypoint.server.create_app_from_config",
        create_app_from_config,
    )
    monkeypatch.setattr("EvernightAI.entrypoint.server.uvicorn.run", run)

    exit_code = package_server_main(["--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert calls == {
        "database_path": (tmp_path / "runtime.sqlite3").as_posix(),
        "app": app,
        "host": "0.0.0.0",
        "port": 8123,
        "reload": True,
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
        "list_directory",
    ]
