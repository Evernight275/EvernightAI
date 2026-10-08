from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from EvernightAI.bootstrap.http import create_app_from_config
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.schema.auth import Principal
from EvernightAI.interface.cli.commands import redact_config
from EvernightAI.interface.cli.config import parse_config
from EvernightAI.interface.cli.schema import EvernightConfig
from EvernightAI.core.schema.agent import AgentTraceEvent, AgentTraceEventType
from EvernightAI.core.schema.stream import WebSocketMessage, WebSocketMessageType
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import PasswordLoginHttpAuthDevice
from EvernightAI.interface.http.websocket import WebSocketConnectionManager
from EvernightAI.interface.http.schema import HttpPasswordCredential


def make_device(
    *,
    session_ttl_seconds: float = 60,
    clock: "Clock | None" = None,
) -> PasswordLoginHttpAuthDevice:
    return PasswordLoginHttpAuthDevice(
        [
            HttpPasswordCredential(
                username="admin",
                password="correct horse",
                principal=Principal(principal_id="admin", permissions=["*"]),
            )
        ],
        session_ttl_seconds=session_ttl_seconds,
        clock=clock,
    )


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def make_config(tmp_path: Path, auth: dict[str, object]) -> EvernightConfig:
    return parse_config(
        {
            "runtime": {"database_path": (tmp_path / "runtime.sqlite3").as_posix()},
            "auth": {"enabled": True, **auth},
        }
    )


@asynccontextmanager
async def serve(config: EvernightConfig) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app_from_config(config)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            yield client


def bearer(access_token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {access_token}"}


def test_login_issues_distinct_session_tokens_for_the_configured_user() -> None:
    device = make_device()

    first = device.login("admin", "correct horse")
    second = device.login("admin", "correct horse")

    assert first.access_token != second.access_token
    assert device.principal(first.access_token).principal_id == "admin"
    assert device.principal(second.access_token).principal_id == "admin"


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("admin", "wrong"),
        ("admin", ""),
        ("unknown", "correct horse"),
        ("unknown", ""),
        ("Admin", "correct horse"),
    ],
)
def test_login_rejects_bad_credentials_without_revealing_which_part_failed(
    username: str,
    password: str,
) -> None:
    with pytest.raises(AuthRequiredError) as exc_info:
        make_device().login(username, password)

    assert str(exc_info.value) == "Invalid username or password"


def test_password_is_not_accepted_as_a_session_token() -> None:
    with pytest.raises(AuthRequiredError):
        make_device().principal("correct horse")


def test_session_expires_after_its_ttl() -> None:
    clock = Clock()
    device = make_device(session_ttl_seconds=60, clock=clock)
    session = device.login("admin", "correct horse")
    assert session.expires_at == clock.now + timedelta(seconds=60)

    clock.now += timedelta(seconds=59)
    assert device.principal(session.access_token).principal_id == "admin"

    clock.now += timedelta(seconds=1)
    with pytest.raises(AuthRequiredError, match="expired"):
        device.principal(session.access_token)
    with pytest.raises(AuthRequiredError, match="Invalid access token"):
        device.principal(session.access_token)


@pytest.mark.asyncio
async def test_configured_user_logs_in_uses_the_api_and_logs_out(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, {"user": {"admin": {"password": "correct horse"}}})

    async with serve(config) as client:
        assert (await client.get("/auth/me")).status_code == 401
        assert (await client.get("/tools")).status_code == 401

        denied = await client.post(
            "/auth/login", json={"username": "admin", "password": "wrong"}
        )
        assert denied.status_code == 401
        assert denied.headers["cache-control"] == "no-store"

        login = await client.post(
            "/auth/login", json={"username": "admin", "password": "correct horse"}
        )
        assert login.status_code == 200
        assert login.headers["cache-control"] == "no-store"
        body = login.json()
        assert body["token_type"] == "bearer"
        assert body["principal"] == {
            "principal_id": "admin",
            "principal_type": "user",
            "roles": [],
            "permissions": ["*"],
        }
        assert "correct horse" not in login.text
        headers = bearer(body["access_token"])

        identity = await client.get("/auth/me", headers=headers)
        assert identity.status_code == 200
        assert identity.json()["login_enabled"] is True
        assert identity.json()["principal"]["principal_id"] == "admin"
        assert (await client.get("/tools", headers=headers)).status_code == 200

        assert (await client.post("/auth/logout", headers=headers)).status_code == 204
        assert (await client.get("/auth/me", headers=headers)).status_code == 401
        assert (await client.get("/tools", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_logged_in_user_is_limited_to_configured_permissions(
    tmp_path: Path,
) -> None:
    config = make_config(
        tmp_path,
        {
            "user": {
                "viewer": {"password": "read only", "permissions": ["tools:list"]},
            }
        },
    )

    async with serve(config) as client:
        login = await client.post(
            "/auth/login", json={"username": "viewer", "password": "read only"}
        )
        headers = bearer(login.json()["access_token"])

        assert (await client.get("/tools", headers=headers)).status_code == 200
        assert (await client.get("/providers", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_login_sessions_coexist_with_api_keys(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        {
            "user": {"admin": {"password": "correct horse"}},
            "principal": {"service": {"api_key": "service-key", "permissions": ["*"]}},
        },
    )

    async with serve(config) as client:
        login = await client.post(
            "/auth/login", json={"username": "admin", "password": "correct horse"}
        )
        by_session = await client.get(
            "/auth/me", headers=bearer(login.json()["access_token"])
        )
        by_api_key = await client.get(
            "/auth/me", headers={"x-evernight-api-key": "service-key"}
        )
        # An API key is not a login session, so logging out with it revokes nothing.
        logout = await client.post("/auth/logout", headers=bearer("service-key"))
        still_valid = await client.get("/auth/me", headers=bearer("service-key"))

    assert by_session.json()["principal"]["principal_id"] == "admin"
    assert by_api_key.json()["principal"]["principal_id"] == "service"
    assert logout.status_code == 204
    assert still_valid.status_code == 200


@pytest.mark.asyncio
async def test_user_and_api_key_with_the_same_name_share_owned_data(
    tmp_path: Path,
) -> None:
    config = make_config(
        tmp_path,
        {
            "user": {"admin": {"password": "correct horse"}},
            "principal": {
                "admin": {"api_key": "admin-key", "permissions": ["*"]},
                "service": {"api_key": "service-key", "permissions": ["*"]},
            },
        },
    )

    async with serve(config) as client:
        created = await client.post(
            "/contexts",
            json={"context_id": "ctx-shared"},
            headers={"x-evernight-api-key": "admin-key"},
        )
        login = await client.post(
            "/auth/login", json={"username": "admin", "password": "correct horse"}
        )
        as_user = await client.get(
            "/contexts/ctx-shared", headers=bearer(login.json()["access_token"])
        )
        as_other_key = await client.get(
            "/contexts/ctx-shared", headers={"x-evernight-api-key": "service-key"}
        )

    assert created.status_code == 201
    assert as_user.status_code == 200
    assert as_user.json()["owner_id"] == "admin"
    assert as_other_key.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("auth", "expected"),
    [
        (
            {"enabled": True, "user": {"admin": {"password": "correct horse"}}},
            {"authentication_enabled": True, "login_enabled": True},
        ),
        (
            {"enabled": True, "principal": {"service": {"api_key": "service-key"}}},
            {"authentication_enabled": True, "login_enabled": False},
        ),
        (
            {"enabled": False, "user": {"admin": {"password": "correct horse"}}},
            {"authentication_enabled": False, "login_enabled": False},
        ),
    ],
)
async def test_signed_out_client_can_discover_how_to_sign_in(
    tmp_path: Path,
    auth: dict[str, object],
    expected: dict[str, bool],
) -> None:
    config = make_config(tmp_path, auth)

    async with serve(config) as client:
        response = await client.get("/auth/config")

    assert response.status_code == 200
    assert response.json() == expected
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_login_is_unavailable_without_configured_users(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        {"principal": {"service": {"api_key": "service-key", "permissions": ["*"]}}},
    )

    async with serve(config) as client:
        login = await client.post(
            "/auth/login", json={"username": "admin", "password": "anything"}
        )
        identity = await client.get(
            "/auth/me", headers={"x-evernight-api-key": "service-key"}
        )

    assert login.status_code == 404
    assert identity.json()["login_enabled"] is False


@pytest.mark.asyncio
async def test_logout_requires_a_bearer_token(tmp_path: Path) -> None:
    config = make_config(tmp_path, {"user": {"admin": {"password": "correct horse"}}})

    async with serve(config) as client:
        assert (await client.post("/auth/logout")).status_code == 401


def test_config_reads_user_password_from_environment_and_redacts_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_ADMIN_PASSWORD", "from-environment")

    config = parse_config(
        {
            "auth": {
                "enabled": True,
                "login_session_ttl_seconds": 900,
                "user": {
                    "admin": {"password_env": "TEST_ADMIN_PASSWORD"},
                    "viewer": {"password": "inline", "permissions": []},
                },
            }
        }
    )

    admin, viewer = config.auth.users
    assert (admin.username, admin.password) == ("admin", "from-environment")
    assert admin.permissions == ["*"]
    assert viewer.permissions == []
    assert config.auth.login_session_ttl_seconds == 900
    redacted = str(redact_config(config))
    assert "from-environment" not in redacted
    assert "inline" not in redacted


def test_user_without_a_password_fails_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_MISSING_PASSWORD", raising=False)
    config = make_config(
        tmp_path,
        {"user": {"admin": {"password_env": "TEST_MISSING_PASSWORD"}}},
    )

    with pytest.raises(ConfigurationError, match="admin"):
        create_app_from_config(config)


@pytest.mark.asyncio
async def test_login_validation_error_does_not_echo_the_password(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, {"user": {"admin": {"password": "correct horse"}}})

    async with serve(config) as client:
        response = await client.post("/auth/login", json={"password": "correct horse"})

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert "correct horse" not in response.text
    assert response.json()["error"]["detail"][0]["loc"] == ["body", "username"]


@pytest.mark.asyncio
async def test_openapi_leaves_login_public_and_secures_logout(tmp_path: Path) -> None:
    config = make_config(tmp_path, {"user": {"admin": {"password": "correct horse"}}})

    async with serve(config) as client:
        paths = (await client.get("/openapi.json")).json()["paths"]

    assert "security" not in paths["/auth/login"]["post"]
    assert "security" not in paths["/auth/config"]["get"]
    assert paths["/auth/logout"]["post"]["security"]
    assert paths["/auth/me"]["get"]["security"]


def make_login_app(device: PasswordLoginHttpAuthDevice) -> FastAPI:
    return create_http_app(
        create_interface(create_runtime()),
        auth_device=device,
        login_device=device,
        close_on_shutdown=False,
    )


SUBSCRIBE = {
    "message_type": "client_event",
    "message_id": "subscribe-1",
    "client_event": {
        "event_name": "agent_run.subscribe",
        "payload": {"run_id": "run-1"},
    },
}


def test_websocket_opened_before_logout_is_closed_on_its_next_message() -> None:
    device = make_device()
    access_token = device.login("admin", "correct horse").access_token

    with TestClient(make_login_app(device)) as client:
        with client.websocket_connect(f"/ws?access_token={access_token}") as websocket:
            assert websocket.receive_json()["message_type"] == "hello"
            logout = client.post("/auth/logout", headers=bearer(access_token))
            websocket.send_json(SUBSCRIBE)
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert logout.status_code == 204
    assert exc_info.value.code == 1008
    assert exc_info.value.reason == "AuthRequiredError"


def test_websocket_is_closed_once_its_login_session_expires() -> None:
    clock = Clock()
    device = make_device(session_ttl_seconds=60, clock=clock)
    access_token = device.login("admin", "correct horse").access_token

    with TestClient(make_login_app(device)) as client:
        with client.websocket_connect(f"/ws?access_token={access_token}") as websocket:
            assert websocket.receive_json()["message_type"] == "hello"
            clock.now += timedelta(seconds=60)
            websocket.send_json(SUBSCRIBE)
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1008


def test_websocket_rejects_session_expiring_during_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    device = make_device(session_ttl_seconds=60, clock=clock)
    access_token = device.login("admin", "correct horse").access_token
    principal_for_token = device.principal

    def authenticate_then_expire(credential: object) -> Principal:
        principal = principal_for_token(credential)
        clock.now += timedelta(seconds=60)
        return principal

    monkeypatch.setattr(device, "principal", authenticate_then_expire)

    with TestClient(make_login_app(device)) as client:
        with client.websocket_connect(f"/ws?access_token={access_token}") as websocket:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1008


class RecordingWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.close_codes: list[int] = []

    async def accept(self, subprotocol: str | None = None) -> None:
        pass

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.close_codes.append(code)


def trace_message(sequence: int) -> WebSocketMessage:
    return WebSocketMessage(
        message_type=WebSocketMessageType.AGENT_TRACE,
        run_id="run-1",
        trace_event=AgentTraceEvent(
            sequence=sequence,
            event_type=AgentTraceEventType.CHAT_DELTA,
        ),
        payload={"sequence": sequence, "replayed": False},
    )


@pytest.mark.asyncio
async def test_subscribed_websocket_stops_receiving_trace_once_its_session_ends() -> (
    None
):
    clock = Clock()
    device = make_device(session_ttl_seconds=60, clock=clock)
    access_token = device.login("admin", "correct horse").access_token
    revoked: Any = RecordingWebSocket()
    other: Any = RecordingWebSocket()
    manager = WebSocketConnectionManager(
        heartbeat_interval_seconds=60.0,
        heartbeat_timeout_seconds=120.0,
    )
    connection = await manager.connect(revoked, connection_id="revoked")
    connection.guard_credential(device.session_guard(access_token))
    bystander = await manager.connect(other, connection_id="other")
    manager.subscribe(connection, "run-1")
    manager.subscribe(bystander, "run-1")

    await manager.broadcast_run("run-1", trace_message(1))
    clock.now += timedelta(seconds=60)
    await manager.broadcast_run("run-1", trace_message(2))
    await manager.disconnect(bystander)

    assert [message["payload"]["sequence"] for message in revoked.sent] == [1]
    assert [message["payload"]["sequence"] for message in other.sent] == [1, 2]
    assert revoked.close_codes == [1008]
    assert manager.connection_count == 0


@pytest.mark.asyncio
async def test_idle_websocket_is_closed_by_heartbeat_once_its_session_ends() -> None:
    clock = Clock()
    device = make_device(session_ttl_seconds=60, clock=clock)
    access_token = device.login("admin", "correct horse").access_token
    websocket: Any = RecordingWebSocket()
    manager = WebSocketConnectionManager(
        heartbeat_interval_seconds=0.01,
        heartbeat_timeout_seconds=120.0,
    )
    connection = await manager.connect(websocket, connection_id="idle")
    connection.guard_credential(device.session_guard(access_token))
    clock.now += timedelta(seconds=60)

    async with asyncio.timeout(2):
        while not websocket.close_codes:
            await asyncio.sleep(0.01)

    assert websocket.close_codes == [1008]
    assert manager.connection_count == 0


def test_session_guard_ignores_tokens_that_are_not_login_sessions() -> None:
    assert make_device().session_guard("service-key") is None
    assert make_device().session_guard(None) is None
