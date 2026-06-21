from fastapi.testclient import TestClient

from EvernightAI.server import create_app


def test_server_factory_creates_http_app(tmp_path) -> None:
    app = create_app(
        database_path=tmp_path / "runtime.sqlite3",
        filesystem_root=tmp_path,
        close_on_shutdown=False,
    )

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
