from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Scope, Receive, Send
from starlette.websockets import WebSocketDisconnect

from EvernightAI.bootstrap.config import _cli_principal
from EvernightAI.bootstrap.http import create_app_from_config
from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.interface.cli.config import parse_config
from EvernightAI.interface.cli.schema import EvernightConfig


def make_config(tmp_path: Path) -> EvernightConfig:
    return parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "auth": {
                "enabled": True,
                "user": {
                    "alice": {
                        "password": "alice-password",
                        "permissions": ["tools:list"],
                    },
                    "bob": {"password": "bob-password"},
                },
                "principal": {
                    "legacy": {
                        "api_key": "legacy-secret",
                        "api_key_env": "LEGACY_AUTH_KEY",
                    }
                },
            },
        }
    )


@contextmanager
def serve(config: EvernightConfig) -> Iterator[TestClient]:
    # Assemble and close the runtime on the server thread, as in production.
    app: FastAPI | None = None

    async def server(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal app
        if app is None:
            app = create_app_from_config(config)
        await app(scope, receive, send)

    with TestClient(server) as client:
        yield client


def login(client: TestClient, username: str = "alice") -> dict[str, str]:
    response = client.post(
        "/auth/login", json={"username": username, "password": username + "-password"}
    )
    assert response.status_code == 200
    return {"authorization": "Bearer " + response.json()["access_token"]}


def test_create_list_revoke_require_account_login_and_keep_owner_scope(
    tmp_path: Path,
) -> None:
    with serve(make_config(tmp_path)) as client:
        alice = login(client)
        bob = login(client, "bob")
        created = client.post(
            "/auth/api-keys",
            json={"name": " automation ", "owner_id": "bob", "permissions": ["*"]},
            headers=alice,
        )
        assert created.status_code == 201
        assert created.headers["cache-control"] == "no-store"
        issued = created.json()
        key_id = issued["key"]["key_id"]
        api_key = issued["api_key"]
        key_headers = {"authorization": "Bearer " + api_key}
        assert issued["key"]["owner_id"] == "alice"
        assert issued["key"]["name"] == "automation"
        assert client.get("/tools", headers=key_headers).status_code == 200
        assert client.get("/providers", headers=key_headers).status_code == 403
        assert (
            client.get("/auth/me", headers={"x-evernight-api-key": api_key}).json()[
                "principal"
            ]["principal_id"]
            == "alice"
        )
        listed = client.get("/auth/api-keys", headers=alice)
        assert listed.json() == [issued["key"]]
        assert api_key not in listed.text
        assert client.get("/auth/api-keys", headers=bob).json() == []
        for headers in [{}, key_headers, {"x-evernight-api-key": api_key}]:
            for method, path, kwargs in [
                ("GET", "/auth/api-keys", {}),
                ("POST", "/auth/api-keys", {"json": {"name": "unauthorized"}}),
                ("DELETE", f"/auth/api-keys/{key_id}", {}),
            ]:
                response = client.request(method, path, headers=headers, **kwargs)
                assert response.status_code == 401
                assert response.headers["cache-control"] == "no-store"
        assert client.delete(f"/auth/api-keys/{key_id}", headers=bob).status_code == 404
        assert client.get("/tools", headers=key_headers).status_code == 200
        for _ in range(2):
            assert (
                client.delete(f"/auth/api-keys/{key_id}", headers=alice).status_code
                == 204
            )
        assert client.get("/tools", headers=key_headers).status_code == 401
        assert client.get("/tools", headers=alice).status_code == 200
        assert (
            client.get("/auth/api-keys", headers=alice).json()[0]["revoked_at"]
            is not None
        )
        assert (
            client.get(
                "/auth/me", headers={"x-evernight-api-key": "legacy-secret"}
            ).status_code
            == 401
        )
        paths = client.get("/openapi.json").json()["paths"]
        for path in ["/auth/api-keys", "/auth/api-keys/{key_id}"]:
            for operation in paths[path].values():
                assert operation["security"] == [{"EvernightBearerAuth": []}]


def test_keys_survive_restart_and_follow_current_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    with serve(config) as client:
        session = login(client)
        issued = client.post(
            "/auth/api-keys", json={"name": "persistent"}, headers=session
        ).json()
    key_headers = {"x-evernight-api-key": issued["api_key"]}
    config.auth.users[0].permissions = ["providers:list"]
    with serve(config) as client:
        assert client.get("/auth/me", headers=session).status_code == 401
        assert client.get("/auth/me", headers=key_headers).json()["principal"][
            "permissions"
        ] == ["providers:list"]
        assert client.get("/tools", headers=key_headers).status_code == 403
        monkeypatch.setenv("EVERNIGHTAI_CLI_API_KEY", issued["api_key"])
        assert _cli_principal(config).principal_id == "alice"
        new_session = login(client)
        assert (
            client.delete(
                "/auth/api-keys/" + issued["key"]["key_id"], headers=new_session
            ).status_code
            == 204
        )
        with pytest.raises(AuthRequiredError):
            _cli_principal(config)
    with serve(config) as client:
        assert client.get("/auth/me", headers=key_headers).status_code == 401


def test_removed_account_cannot_use_its_persisted_key(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    with serve(config) as client:
        issued = client.post(
            "/auth/api-keys", json={"name": "persistent"}, headers=login(client)
        ).json()
    config.auth.users = [user for user in config.auth.users if user.username != "alice"]
    with serve(config) as client:
        assert (
            client.get(
                "/auth/me", headers={"x-evernight-api-key": issued["api_key"]}
            ).status_code
            == 401
        )


@pytest.mark.parametrize(
    "payload, status",
    [
        ({"name": " "}, 400),
        ({"name": "x", "expires_at": "2000-01-01T00:00:00Z"}, 400),
        ({"name": "x", "expires_at": "2100-01-01T00:00:00"}, 400),
        ({"name": ""}, 400),
    ],
)
def test_invalid_key_requests_do_not_create_keys(
    tmp_path: Path, payload: dict[str, str], status: int
) -> None:
    with serve(make_config(tmp_path)) as client:
        session = login(client)
        response = client.post("/auth/api-keys", json=payload, headers=session)
        assert response.status_code == status
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/auth/api-keys", headers=session).json() == []


@pytest.mark.parametrize("header", [False, True])
def test_revoking_a_key_closes_its_existing_websocket(
    tmp_path: Path, header: bool
) -> None:
    with serve(make_config(tmp_path)) as client:
        session = login(client)
        issued = client.post(
            "/auth/api-keys", json={"name": "socket"}, headers=session
        ).json()
        path = "/ws" if header else "/ws?access_token=" + issued["api_key"]
        headers = {"x-evernight-api-key": issued["api_key"]} if header else {}
        with client.websocket_connect(path, headers=headers) as websocket:
            assert websocket.receive_json()["message_type"] == "hello"
            assert (
                client.delete(
                    "/auth/api-keys/" + issued["key"]["key_id"], headers=session
                ).status_code
                == 204
            )
            websocket.send_json(
                {
                    "message_type": "client_event",
                    "client_event": {
                        "event_name": "agent_run.subscribe",
                        "payload": {"run_id": "run-1"},
                    },
                }
            )
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()
        assert exc_info.value.code == 1008


@pytest.mark.parametrize("enabled, users", [(False, True), (True, False)])
def test_key_management_is_unavailable_without_account_login(
    tmp_path: Path, enabled: bool, users: bool
) -> None:
    config = make_config(tmp_path)
    config.auth.enabled = enabled
    if not users:
        config.auth.users = []
    with serve(config) as client:
        for method, path, kwargs in [
            ("GET", "/auth/api-keys", {}),
            ("POST", "/auth/api-keys", {"json": {"name": "automation"}}),
            ("DELETE", "/auth/api-keys/missing", {}),
        ]:
            response = client.request(method, path, **kwargs)
            assert response.status_code == 404
            assert response.headers["cache-control"] == "no-store"


def test_external_bearer_tokens_cannot_manage_keys(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config.auth.oauth = parse_config(
        {
            "auth": {
                "oauth": {
                    "token": {
                        "alice": {
                            "access_token": "external-token",
                            "permissions": ["*"],
                        }
                    }
                }
            }
        }
    ).auth.oauth
    with serve(config) as client:
        headers = {"authorization": "Bearer external-token"}
        assert client.get("/auth/me", headers=headers).status_code == 200
        assert client.get("/auth/api-keys", headers=headers).status_code == 401
        assert (
            client.post(
                "/auth/api-keys", json={"name": "blocked"}, headers=headers
            ).status_code
            == 401
        )
