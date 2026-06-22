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
