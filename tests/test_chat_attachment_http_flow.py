import asyncio
import base64
import json
import struct
import zlib
from typing import Any

from fastapi.testclient import TestClient

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.provider import (
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import ApiKeyHttpAuthDevice
from EvernightAI.interface.http.schema import HttpApiKeyCredential
from tests.fakes.streams import EventStream


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def _one_pixel_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0),
        )
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + _png_chunk(b"IEND", b"")
    )


PNG = _one_pixel_png()
PNG_DATA_URI = "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")


ALICE_PERMISSIONS = [
    "files:create",
    "contexts:create",
    "contexts:get",
    "providers:create",
    "chat:create",
    "chat:stream",
    "agent-runs:create",
    "agent-runs:stream",
    "agent-runs:get",
]


class RecordingVisionProvider(ProviderInstanceProtocol):
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def list_models(self) -> list[ProviderModelConfig]:
        return [
            ProviderModelConfig(
                model_id="vision-model",
                capabilities=[ProviderModelCapability.CHAT],
            )
        ]

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return ProviderModelConfig(
            model_id=model_id,
            capabilities=[ProviderModelCapability.CHAT],
        )

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return capability is ProviderModelCapability.CHAT

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            model_id=request.model_id,
            message=Content(
                role=MessageRole.ASSISTANT,
                content=[ContentPart(type=ContentPartType.TEXT, text="seen")],
            ),
            finish_reason="stop",
        )

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        self.requests.append(request)
        return EventStream(
            [
                ChatStreamEvent(
                    event_type=ChatStreamEventType.MESSAGE_DELTA,
                    model_id=request.model_id,
                    role=MessageRole.ASSISTANT,
                    text_delta="seen",
                ),
                ChatStreamEvent(
                    event_type=ChatStreamEventType.DONE,
                    model_id=request.model_id,
                    finish_reason="stop",
                ),
            ]
        )

    async def close(self) -> None:
        return None


def _http_app(runtime: Any) -> Any:
    interface = create_interface(runtime)
    auth_device = ApiKeyHttpAuthDevice(
        [
            HttpApiKeyCredential(
                api_key="alice-key",
                principal=Principal(
                    principal_id="alice",
                    permissions=ALICE_PERMISSIONS,
                ),
            ),
            HttpApiKeyCredential(
                api_key="bob-key",
                principal=Principal(
                    principal_id="bob",
                    permissions=[
                        "chat:create",
                        "chat:stream",
                        "files:get",
                        "files:read",
                    ],
                ),
            ),
        ]
    )
    return create_http_app(
        interface,
        auth_device=auth_device,
        authorized_interface_factory=lambda current, principal: AuthorizedEvernightInterface(
            current,
            Authorizer(PermissionAuthPolicy()),
            principal,
        ),
        close_on_shutdown=False,
    )


def _register_provider(client: TestClient) -> None:
    response = client.post(
        "/providers",
        headers={"x-evernight-api-key": "alice-key"},
        json={"provider_id": "vision", "name": "Vision", "type": "openai"},
    )
    assert response.status_code == 201, response.text


def _image_message(artifact_id: str) -> dict[str, object]:
    return {
        "role": "user",
        "content": [{"type": "image", "artifact_id": artifact_id}],
    }


def _assert_provider_saw_inline_image(request: ChatRequest) -> None:
    image_parts = [
        part
        for message in request.messages
        for part in message.content or []
        if part.type is ContentPartType.IMAGE
    ]
    assert image_parts
    assert any(part.data == PNG_DATA_URI and part.artifact_id is None for part in image_parts)


def _assert_refs_persisted_without_bytes(payload: dict[str, Any], artifact_id: str) -> None:
    serialized = json.dumps(payload)
    assert artifact_id in serialized
    assert PNG_DATA_URI not in serialized
    assert base64.b64encode(PNG).decode("ascii") not in serialized


def test_uploaded_image_refs_resolve_transiently_across_http_flows_and_sqlite_restart(
    tmp_path,
) -> None:
    database = tmp_path / "attachments.sqlite3"
    provider = RecordingVisionProvider()
    runtime = create_sqlite_runtime(database)
    runtime.provider_factory.register(
        ProviderType.OPENAI,
        lambda _config: _build_provider(provider),
    )
    app = _http_app(runtime)

    with TestClient(app) as client:
        _register_provider(client)
        headers = {"x-evernight-api-key": "alice-key"}
        upload = client.post(
            "/files/upload",
            params={"filename": "tiny.png"},
            content=PNG,
            headers={**headers, "content-type": "application/octet-stream"},
        )
        assert upload.status_code == 201, upload.text
        artifact_id = upload.json()["artifact_id"]
        assert upload.json()["mime_type"] == "image/png"

        created = client.post(
            "/contexts",
            headers=headers,
            json={"context_id": "attachment-context", "messages": []},
        )
        assert created.status_code == 201, created.text

        context_stream = client.post(
            "/chat/context/stream",
            headers=headers,
            json={
                "provider_id": "vision",
                "context_id": "attachment-context",
                "model_id": "vision-model",
                "messages": [_image_message(artifact_id)],
            },
        )
        assert context_stream.status_code == 200, context_stream.text
        assert "chat.message_delta" in context_stream.text
        _assert_provider_saw_inline_image(provider.requests[-1])

        direct_stream = client.post(
            "/chat/stream",
            headers=headers,
            json={
                "provider_id": "vision",
                "request": {
                    "model_id": "vision-model",
                    "messages": [_image_message(artifact_id)],
                },
            },
        )
        assert direct_stream.status_code == 200, direct_stream.text
        _assert_provider_saw_inline_image(provider.requests[-1])

        agent_stream = client.post(
            "/agent-runs/stream",
            headers=headers,
            json={
                "provider_id": "vision",
                "owner_id": "bob",
                "context_id": "attachment-context",
                "model_id": "vision-model",
                "messages": [_image_message(artifact_id)],
                "max_tool_rounds": 0,
                "metadata": {"run_id": "attachment-run", "stream": True},
            },
        )
        assert agent_stream.status_code == 200, agent_stream.text
        _assert_provider_saw_inline_image(provider.requests[-1])

        context = client.get("/contexts/attachment-context", headers=headers)
        run = client.get("/agent-runs/attachment-run", headers=headers)
        assert context.status_code == 200, context.text
        assert run.status_code == 200, run.text
        _assert_refs_persisted_without_bytes(context.json(), artifact_id)
        _assert_refs_persisted_without_bytes(run.json(), artifact_id)
        assert run.json()["owner_id"] == "alice"

        bob_headers = {"x-evernight-api-key": "bob-key"}
        requests_before_bob = len(provider.requests)
        assert client.get(f"/files/{artifact_id}", headers=bob_headers).status_code == 404
        denied = client.post(
            "/chat/stream",
            headers=bob_headers,
            json={
                "provider_id": "vision",
                "request": {
                    "model_id": "vision-model",
                    "messages": [_image_message(artifact_id)],
                },
            },
        )
        assert denied.status_code == 200
        assert "chat.error" in denied.text
        assert len(provider.requests) == requests_before_bob

    asyncio.run(runtime.close())

    reopened_provider = RecordingVisionProvider()
    reopened = create_sqlite_runtime(database)
    reopened.provider_factory.register(
        ProviderType.OPENAI,
        lambda _config: _build_provider(reopened_provider),
    )
    with TestClient(_http_app(reopened)) as client:
        _register_provider(client)
        restored = client.post(
            "/chat/context/stream",
            headers={"x-evernight-api-key": "alice-key"},
            json={
                "provider_id": "vision",
                "context_id": "attachment-context",
                "model_id": "vision-model",
                "messages": [],
            },
        )
        assert restored.status_code == 200, restored.text
        assert reopened_provider.requests
        _assert_provider_saw_inline_image(reopened_provider.requests[0])
        persisted = client.get(
            "/contexts/attachment-context",
            headers={"x-evernight-api-key": "alice-key"},
        )
        assert persisted.status_code == 200
        _assert_refs_persisted_without_bytes(persisted.json(), artifact_id)

    asyncio.run(reopened.close())


async def _build_provider(provider: RecordingVisionProvider) -> RecordingVisionProvider:
    return provider
