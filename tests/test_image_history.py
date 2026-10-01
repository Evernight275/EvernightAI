import asyncio
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl

from EvernightAI.application.image import ImageApplication
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.image import ImageGenerationStore
from EvernightAI.core.error.image import (
    ImageRecordConflictError,
    ImageRecordNotFoundError,
)
from EvernightAI.core.protocol.image import (
    ImageArchiveProtocol,
    ImageGenerationStoreProtocol,
)
from EvernightAI.core.schema.auth import Principal, PrincipalScope
from EvernightAI.core.schema.image import (
    GeneratedImage,
    ImageGenerationRecord,
    ImageGenerationResponse,
)
from EvernightAI.core.schema.provider import ProviderConfig, ProviderType
from EvernightAI.infra.adapters.images.archive import PublicImageArchive
from EvernightAI.infra.adapters.images.sqlite import SQLiteImageGenerationStore
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import ApiKeyHttpAuthDevice
from EvernightAI.interface.http.schema import HttpApiKeyCredential
from tests.test_image_generation import ImageProvider, PNG, request
from tests.test_interface_http import make_runtime


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    result = (
        ImageGenerationStore()
        if request.param == "memory"
        else SQLiteImageGenerationStore(tmp_path / "images.sqlite3")
    )
    yield result
    if isinstance(result, SQLiteImageGenerationStore):
        result.close()


def make_record(owner: str, *, number: int = 1) -> ImageGenerationRecord:
    return ImageGenerationRecord(
        record_id=f"image-{number}",
        owner_id=owner,
        provider_id="main",
        request=request(),
        response=ImageGenerationResponse(
            model_id="image-model",
            images=[GeneratedImage(base64_data=PNG, mime_type="image/png")],
        ),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
        + timedelta(seconds=number),
    )


def test_store_isolates_history_and_payload_by_owner(
    store: ImageGenerationStoreProtocol,
) -> None:
    alice, bob = PrincipalScope(owner_id="alice"), PrincipalScope(owner_id="bob")
    first = make_record("alice")
    store.save(first)
    store.save(make_record("bob", number=2))
    first.request.prompt = "changed outside store"
    record = store.get(first.record_id, principal_scope=alice)
    assert record.request.prompt == "A green leaf"
    record.response.images.clear()
    assert store.get(first.record_id, principal_scope=alice).response.images
    assert [
        item.record_id for item in store.list_records(limit=20, principal_scope=alice)
    ] == [first.record_id]
    assert (
        "base64_data"
        not in store.list_records(limit=20, principal_scope=alice)[0].model_dump_json()
    )
    with pytest.raises(ImageRecordNotFoundError):
        store.get(first.record_id, principal_scope=bob)
    with pytest.raises(ImageRecordNotFoundError):
        store.delete(first.record_id, principal_scope=bob)
    with pytest.raises(ImageRecordConflictError):
        store.save(make_record("bob"))
    store.delete(first.record_id, principal_scope=alice)
    with pytest.raises(ImageRecordNotFoundError):
        store.get(first.record_id, principal_scope=alice)


def test_history_cursor_survives_deletion_and_new_records(
    store: ImageGenerationStoreProtocol,
) -> None:
    runtime = make_runtime()
    runtime._image_records = store
    app = ImageApplication(runtime)
    scope = PrincipalScope(owner_id="alice")
    for number in range(1, 5):
        store.save(make_record("alice", number=number))
    first = app.list_records(limit=2, principal_scope=scope)
    assert [item.record_id for item in first.items] == ["image-4", "image-3"]
    store.delete("image-3", principal_scope=scope)
    store.save(make_record("alice", number=5))
    second = app.list_records(limit=2, cursor=first.next_cursor, principal_scope=scope)
    assert [item.record_id for item in second.items] == ["image-2", "image-1"]
    assert second.next_cursor is None


def test_archive_update_cannot_recreate_deleted_record(
    store: ImageGenerationStoreProtocol,
) -> None:
    record = make_record("alice")
    store.save(record)
    store.delete(record.record_id, principal_scope=PrincipalScope(owner_id="alice"))
    with pytest.raises(ImageRecordNotFoundError):
        store.update(record)
    assert store.list_records(limit=20) == []


@pytest.mark.asyncio
async def test_archival_finish_after_deletion_preserves_deletion() -> None:
    provider = ImageProvider()

    async def generate(req):
        provider.requests.append(req)
        return url_response()

    cast(Any, provider).generate_images = generate
    runtime = make_runtime(provider=provider)

    class DeletedArchive(ImageArchiveProtocol):
        async def archive(
            self, response: ImageGenerationResponse
        ) -> ImageGenerationResponse:
            assert response.record_id
            runtime.image_records.delete(response.record_id)
            return response.model_copy(
                update={
                    "images": [GeneratedImage(base64_data=PNG, mime_type="image/png")],
                    "persistence_warning": None,
                }
            )

    runtime._image_archive = DeletedArchive()
    from EvernightAI.core.schema.provider import ProviderConfig, ProviderType

    await runtime.providers.create(
        ProviderConfig(provider_id="main", name="Main", type=ProviderType.OPENAI)
    )
    result = await ImageApplication(runtime).generate("main", request())
    assert result.record_id is None
    assert result.persistence_warning == "record_deleted"
    assert result.images[0].base64_data == PNG
    assert runtime.image_records.list_records(limit=20) == []
    assert len(provider.requests) == 1
    await runtime.close()


@pytest.mark.asyncio
async def test_sqlite_image_history_survives_runtime_restart_without_provider_calls(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.sqlite3"
    runtime = create_sqlite_runtime(database)
    provider = ImageProvider()

    async def build(_config: ProviderConfig) -> ImageProvider:
        return provider

    runtime.provider_factory.register(ProviderType.OPENAI, build)
    await runtime.providers.create(
        ProviderConfig(provider_id="main", name="Images", type=ProviderType.OPENAI)
    )
    response = await create_interface(runtime).providers.generate_images(
        "main", request(), principal_scope=PrincipalScope(owner_id="alice")
    )
    assert response.record_id
    assert response.persistence_warning is None
    await runtime.close()
    restored = create_sqlite_runtime(database)
    try:
        assert (
            restored.image_records.get(
                response.record_id, principal_scope=PrincipalScope(owner_id="alice")
            )
            .response.images[0]
            .base64_data
            == PNG
        )
        assert len(restored.image_records.list_records(limit=20)) == 1
        assert len(provider.requests) == 1
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_save_failure_returns_generated_images_and_does_not_retry_provider() -> (
    None
):
    provider = ImageProvider()
    runtime = make_runtime(provider=provider)
    interface = create_interface(runtime)
    from EvernightAI.core.schema.provider import ProviderConfig, ProviderType

    await runtime.providers.create(
        ProviderConfig(provider_id="main", name="Main", type=ProviderType.OPENAI)
    )

    def fail(_record: ImageGenerationRecord) -> None:
        raise RuntimeError("disk full")

    cast(Any, runtime.image_records).save = fail
    response = await interface.providers.generate_images(
        "main", request(), principal_scope=PrincipalScope(owner_id="alice")
    )
    assert response.persistence_warning == "save_failed"
    assert response.record_id is None
    assert response.images[0].base64_data == PNG
    assert len(provider.requests) == 1
    await runtime.close()


@pytest.mark.asyncio
async def test_cancelled_archival_preserves_already_generated_record() -> None:
    provider = ImageProvider()

    async def generate(req):
        provider.requests.append(req)
        return ImageGenerationResponse(
            model_id=req.model_id,
            images=[GeneratedImage(url=HttpUrl("https://images.example/leaf.png"))],
        )

    cast(Any, provider).generate_images = generate
    runtime = make_runtime(provider=provider)
    started = asyncio.Event()

    class BlockedArchive(ImageArchiveProtocol):
        async def archive(
            self, response: ImageGenerationResponse
        ) -> ImageGenerationResponse:
            started.set()
            await asyncio.Event().wait()
            return response

    runtime._image_archive = BlockedArchive()
    from EvernightAI.core.schema.provider import ProviderConfig, ProviderType

    await runtime.providers.create(
        ProviderConfig(provider_id="main", name="Main", type=ProviderType.OPENAI)
    )
    task = asyncio.create_task(
        ImageApplication(runtime).generate(
            "main", request(), principal_scope=PrincipalScope(owner_id="alice")
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    records = runtime.image_records.list_records(
        limit=20, principal_scope=PrincipalScope(owner_id="alice")
    )
    assert len(records) == 1
    assert not records[0].archived
    assert runtime.image_records.get(records[0].record_id).response.images[0].url
    assert len(provider.requests) == 1
    await runtime.close()


def url_response(
    url: str = "https://images.example/leaf.png",
) -> ImageGenerationResponse:
    return ImageGenerationResponse(
        model_id="image-model", images=[GeneratedImage(url=HttpUrl(url))]
    )


@pytest.mark.asyncio
async def test_url_archive_pins_public_address_preserves_tls_identity_and_redirects() -> (
    None
):
    calls: list[httpx.Request] = []

    async def resolve(host: str, _port: int) -> list[str]:
        assert host == "images.example"
        return ["93.184.216.34"]

    def respond(call: httpx.Request) -> httpx.Response:
        calls.append(call)
        assert call.url.host == "93.184.216.34"
        assert call.headers["host"] == "images.example"
        assert call.extensions["sni_hostname"] == "images.example"
        assert "authorization" not in call.headers and "cookie" not in call.headers
        if len(calls) == 1:
            return httpx.Response(
                302,
                headers={
                    "location": "/archived.png",
                    "set-cookie": "secret=value; Path=/",
                },
            )
        return httpx.Response(200, content=base64.b64decode(PNG))

    response = await PublicImageArchive(
        resolver=resolve, transport=httpx.MockTransport(respond)
    ).archive(url_response())
    assert response.images[0].base64_data == PNG
    assert response.images[0].mime_type == "image/png"
    assert response.persistence_warning is None
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.0.0.1"],
        ["::1"],
        ["169.254.169.254"],
        ["93.184.216.34", "192.168.1.1"],
        [],
    ],
)
async def test_url_archive_blocks_nonpublic_destinations(addresses: list[str]) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return addresses

    def respond(_call: httpx.Request) -> httpx.Response:
        pytest.fail("Blocked addresses must never be requested")

    response = await PublicImageArchive(
        resolver=resolve, transport=httpx.MockTransport(respond)
    ).archive(url_response())
    assert response.persistence_warning == "archive_incomplete"
    assert response.images[0].base64_data is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "private_redirect",
        "oversized",
        "bad_format",
        "unavailable",
        "redirect_loop",
        "credentials",
    ],
)
async def test_url_archive_failures_keep_the_generated_url(mode: str) -> None:
    async def resolve(host: str, _port: int) -> list[str]:
        return ["127.0.0.1"] if host == "private.example" else ["93.184.216.34"]

    def respond(call: httpx.Request) -> httpx.Response:
        if mode == "private_redirect":
            return httpx.Response(
                302, headers={"location": "https://private.example/secret"}
            )
        if mode == "redirect_loop":
            return httpx.Response(302, headers={"location": "/loop"})
        if mode == "unavailable":
            return httpx.Response(503)
        if mode == "credentials":
            pytest.fail("Credential URLs must be blocked")
        return httpx.Response(
            200, content=b"<svg />" if mode == "bad_format" else base64.b64decode(PNG)
        )

    original = url_response(
        "https://user:secret@images.example/leaf.png"
        if mode == "credentials"
        else "https://images.example/leaf.png"
    )
    response = await PublicImageArchive(
        resolver=resolve,
        transport=httpx.MockTransport(respond),
        max_bytes=4 if mode == "oversized" else 100,
    ).archive(original)
    assert response.images[0].url == original.images[0].url
    assert response.persistence_warning == "archive_incomplete"


def test_http_history_ownership_permissions_and_deletion() -> None:
    provider = ImageProvider()
    runtime = make_runtime(provider=provider)
    credentials = [
        HttpApiKeyCredential(
            api_key=name,
            principal=Principal(
                principal_id=name,
                permissions=[
                    "providers:create",
                    "images:generate",
                    "images:list",
                    "images:get",
                    "images:delete",
                ],
            ),
        )
        for name in ["alice", "bob"]
    ]
    credentials.append(
        HttpApiKeyCredential(
            api_key="limited",
            principal=Principal(principal_id="alice", permissions=["images:generate"]),
        )
    )
    app = create_http_app(
        create_interface(runtime),
        auth_device=ApiKeyHttpAuthDevice(credentials),
        authorized_interface_factory=lambda interface, principal: (
            AuthorizedEvernightInterface(
                interface, Authorizer(PermissionAuthPolicy()), principal
            )
        ),
    )
    alice, bob = {"X-Evernight-API-Key": "alice"}, {"X-Evernight-API-Key": "bob"}
    with TestClient(app) as client:
        assert (
            client.post(
                "/providers",
                headers=alice,
                json={"provider_id": "main", "name": "Main", "type": "openai"},
            ).status_code
            == 201
        )
        response = client.post(
            "/images/generations",
            headers=alice,
            json={"provider_id": "main", "request": request().model_dump(mode="json")},
        )
        record_id = response.json()["record_id"]
        path = f"/images/records/{record_id}"
        history = client.get("/images/records", headers=alice)
        assert history.headers["cache-control"] == "no-store"
        assert history.json()["items"][0]["record_id"] == record_id
        assert "base64_data" not in history.text
        assert client.get("/images/records", headers=bob).json()["items"] == []
        assert client.get(path, headers=bob).status_code == 404
        assert client.delete(path, headers=bob).status_code == 404
        assert (
            client.get(path, headers={"X-Evernight-API-Key": "limited"}).status_code
            == 403
        )
        assert (
            client.get(path, headers=alice).json()["response"]["images"][0][
                "base64_data"
            ]
            == PNG
        )
        assert (
            client.get("/images/records?cursor=invalid", headers=alice).status_code
            == 400
        )
        assert client.delete(path, headers=alice).status_code == 204
        assert client.get(path, headers=alice).status_code == 404
        assert client.get("/images/records", headers=alice).json()["items"] == []
        assert len(provider.requests) == 1
