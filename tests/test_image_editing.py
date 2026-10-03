import asyncio
import base64
from datetime import timedelta
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import Any, Literal, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from pydantic import ValidationError

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.error.provider import (
    ProviderCapabilityUnsupportedError,
    ProviderDisabledError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.image import (
    ImageEditInput,
    ImageEditRequest,
    ImageGenerationRecord,
    ImageGenerationResponse,
    MAX_IMAGE_INPUT_BYTES,
    MAX_IMAGE_INPUT_COUNT,
    MAX_IMAGE_INPUT_TOTAL_BYTES,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderConfigUpdate,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.infra.adapters.images.sqlite import SQLiteImageGenerationStore
from EvernightAI.infra.adapters.providers.openai_compatible.instance import (
    OpenAICompatibleProviderInstance,
)
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import ApiKeyHttpAuthDevice
from EvernightAI.interface.http.schema import HttpApiKeyCredential
from tests.test_image_generation import ImageProvider, PNG
from tests.test_interface_http import make_runtime


def edit_request(**kwargs: Any) -> ImageEditRequest:
    return ImageEditRequest(
        **{
            "model_id": "image-model",
            "prompt": "Make the leaf blue",
            "images": [ImageEditInput(base64_data=PNG, mime_type="image/png")],
            **kwargs,
        }
    )


def png_input(number: int) -> ImageEditInput:
    return ImageEditInput(
        base64_data=base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes([number])).decode(),
        mime_type="image/png",
    )


def test_edit_request_accepts_16_images_and_rejects_empty_or_over_limit() -> None:
    images = [png_input(number) for number in range(MAX_IMAGE_INPUT_COUNT)]
    assert edit_request(images=images).images == images
    for values in [[], [*images, png_input(16)]]:
        with pytest.raises(ValidationError):
            edit_request(images=values)


def test_edit_request_enforces_total_decoded_size() -> None:
    def sized_image(size: int) -> ImageEditInput:
        return ImageEditInput(
            base64_data=base64.b64encode(
                b"\x89PNG\r\n\x1a\n" + b"a" * (size - 8)
            ).decode(),
            mime_type="image/png",
        )

    large = sized_image(MAX_IMAGE_INPUT_BYTES)
    remaining = MAX_IMAGE_INPUT_TOTAL_BYTES - 2 * MAX_IMAGE_INPUT_BYTES
    assert edit_request(images=[large, large, sized_image(remaining)])
    with pytest.raises(ValidationError, match="50 MiB"):
        edit_request(images=[large, large, sized_image(remaining + 1)])


def test_single_image_requests_and_saved_records_remain_readable() -> None:
    legacy = {
        "model_id": "image-model",
        "prompt": "Make the leaf blue",
        "image": {"base64_data": PNG, "mime_type": "image/png"},
    }
    request = ImageEditRequest.model_validate(legacy)
    assert request.images == edit_request().images
    assert "image" not in request.model_dump()
    with pytest.raises(ValidationError):
        ImageEditRequest.model_validate({**legacy, "images": [legacy["image"]]})
    response = asyncio.run(EditProvider().edit_images(request))
    record = ImageGenerationRecord.model_validate(
        {"provider_id": "main", "request": legacy, "response": response}
    )
    assert isinstance(record.request, ImageEditRequest)
    assert record.request.images == request.images


@pytest.mark.parametrize(
    "image",
    [
        {"base64_data": "!!", "mime_type": "image/png"},
        {"base64_data": PNG, "mime_type": "image/jpeg"},
        {"base64_data": PNG, "mime_type": "image/svg+xml"},
        {"base64_data": "", "mime_type": "image/png"},
        {"base64_data": base64.b64encode(b"<svg/>").decode(), "mime_type": "image/png"},
        {"url": "https://images.example/original.png", "mime_type": "image/png"},
    ],
)
def test_edit_input_rejects_invalid_or_remote_images(image: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ImageEditInput.model_validate(image)


def test_edit_input_limits_decoded_size_and_does_not_expose_data_in_repr() -> None:
    data = b"\x89PNG\r\n\x1a\n" + b"a" * (MAX_IMAGE_INPUT_BYTES - 8)
    assert ImageEditInput(
        base64_data=base64.b64encode(data).decode(), mime_type="image/png"
    )
    with pytest.raises(ValidationError):
        ImageEditInput(
            base64_data=base64.b64encode(data + b"a").decode(), mime_type="image/png"
        )
    assert PNG not in repr(edit_request())


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [True, False])
@pytest.mark.parametrize("image_count", [1, 16])
@pytest.mark.parametrize(
    ("data", "mime", "filename"),
    [
        (b"\x89PNG\r\n\x1a\nimage", "image/png", "reference-1.png"),
        (b"\xff\xd8\xffimage", "image/jpeg", "reference-1.jpg"),
        (b"RIFFxxxxWEBPimage", "image/webp", "reference-1.webp"),
    ],
)
async def test_edit_sdk_uploads_multipart_without_discovery(
    declared: bool,
    image_count: int,
    data: bytes,
    mime: str,
    filename: str,
) -> None:
    calls: list[httpx.Request] = []

    def respond(call: httpx.Request) -> httpx.Response:
        calls.append(call)
        return httpx.Response(200, json={"created": 123, "data": [{"b64_json": PNG}]})

    instance = OpenAICompatibleProviderInstance(
        ProviderConfig(
            provider_id="main",
            name="Main",
            type=ProviderType.OPENAI,
            model={
                "image": ProviderModelConfig(
                    model_id="image-model",
                    timeout=timedelta(seconds=75),
                    capabilities=[ProviderModelCapability.IMAGE_GENERATION],
                )
            }
            if declared
            else {},
        )
    )
    await instance._client.close()
    instance._client = AsyncOpenAI(
        api_key="test",
        base_url="https://provider.example/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    request = edit_request(
        count=2,
        size="1024x1024",
        quality="high",
        output_format="png",
        background="opaque",
        result_format="base64",
    )
    inputs = [data + bytes([index]) for index in range(image_count)]
    request.images = [
        ImageEditInput(
            base64_data=base64.b64encode(value).decode(),
            mime_type=cast(Literal["image/png", "image/jpeg", "image/webp"], mime),
        )
        for value in inputs
    ]
    try:
        result = await instance.edit_images(request)
        assert result.images[0].mime_type == "image/png"
        assert len(calls) == 1
        call = calls[0]
        assert call.url.path == "/v1/images/edits"
        assert call.extensions["timeout"]["read"] == (75 if declared else 180)
        message = BytesParser(policy=default).parsebytes(
            f"Content-Type: {call.headers['content-type']}\r\n\r\n".encode()
            + call.content
        )
        parts = list(message.iter_parts())
        files = [part for part in parts if part.get_filename()]
        assert len(files) == image_count
        assert [part.get_payload(decode=True) for part in files] == inputs
        assert [part.get_filename() for part in files] == [
            f"reference-{index + 1}.{filename.split('.')[-1]}"
            for index in range(image_count)
        ]
        assert all(part.get_content_type() == mime for part in files)
        assert all(
            part.get_param("name", header="content-disposition")
            == ("image" if image_count == 1 else "image[]")
            for part in files
        )
        assert {
            part.get_param("name", header="content-disposition"): cast(
                bytes, part.get_payload(decode=True)
            ).decode()
            for part in parts
            if not part.get_filename()
        } == {
            "model": "image-model",
            "prompt": "Make the leaf blue",
            "n": "2",
            "size": "1024x1024",
            "quality": "high",
            "output_format": "png",
            "background": "opaque",
            "response_format": "b64_json",
        }
        await instance.edit_images(edit_request(timeout_seconds=42))
        assert calls[-1].extensions["timeout"]["read"] == 42
    finally:
        await instance.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["offline", "bad_request"])
async def test_edit_errors_are_translated_without_retry(failure: str) -> None:
    calls = 0

    def respond(call: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "offline":
            raise httpx.ConnectError("offline", request=call)
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Model does not support editing",
                    "type": "invalid_request_error",
                }
            },
        )

    instance = OpenAICompatibleProviderInstance(
        ProviderConfig(provider_id="main", name="Main", type=ProviderType.OPENAI)
    )
    await instance._client.close()
    instance._client = AsyncOpenAI(
        api_key="test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        with pytest.raises(
            ProviderUnavailableError if failure == "offline" else ProviderRequestError
        ) as caught:
            await instance.edit_images(edit_request())
        if failure == "bad_request":
            assert "Model does not support editing" in str(caught.value)
        assert calls == 1
    finally:
        await instance.close()


class EditProvider(ImageProvider):
    async def edit_images(self, request: ImageEditRequest) -> ImageGenerationResponse:
        return await self.generate_images(request)


@pytest.mark.asyncio
async def test_edit_manager_releases_retired_provider_after_cancellation() -> None:
    provider = EditProvider(blocked=True)
    factory = ProviderFactory()

    async def build(_config: ProviderConfig) -> ImageProvider:
        return provider

    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory)
    await manager.create(
        ProviderConfig(provider_id="main", name="Main", type=ProviderType.OPENAI)
    )
    task = asyncio.create_task(manager.edit_images("main", edit_request()))
    await asyncio.wait_for(provider.started.wait(), 2)
    await manager.update("main", ProviderConfigUpdate(is_enabled=False))
    assert not provider.closed
    with pytest.raises(ProviderDisabledError):
        await manager.edit_images("main", edit_request())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.closed
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("unsupported", ["adapter", "model"])
async def test_edit_manager_rejects_unsupported_adapter_or_model(
    unsupported: str,
) -> None:
    provider = ImageProvider() if unsupported == "adapter" else EditProvider()
    factory = ProviderFactory()

    async def build(_config: ProviderConfig) -> ImageProvider:
        return provider

    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory)
    await manager.create(
        ProviderConfig(
            provider_id="main",
            name="Main",
            type=ProviderType.OPENAI,
            model={
                "image": ProviderModelConfig(
                    model_id="image-model", capabilities=[ProviderModelCapability.CHAT]
                )
            }
            if unsupported == "model"
            else {},
        )
    )
    try:
        with pytest.raises(ProviderCapabilityUnsupportedError):
            await manager.edit_images("main", edit_request())
        assert not provider.requests
    finally:
        await manager.close()


@pytest.mark.parametrize("allowed", [True, False])
def test_edit_http_permission_ownership_validation_and_history(allowed: bool) -> None:
    provider = EditProvider()
    runtime = make_runtime(provider=provider)
    permissions = ["providers:create", "images:list", "images:get", "images:delete"] + (
        ["images:generate"] if allowed else []
    )
    app = create_http_app(
        create_interface(runtime),
        auth_device=ApiKeyHttpAuthDevice(
            [
                HttpApiKeyCredential(
                    api_key=owner,
                    principal=Principal(principal_id=owner, permissions=permissions),
                )
                for owner in ["alice", "bob"]
            ]
        ),
        authorized_interface_factory=lambda interface, principal: (
            AuthorizedEvernightInterface(
                interface, Authorizer(PermissionAuthPolicy()), principal
            )
        ),
    )
    with TestClient(app) as client:
        headers = {"X-Evernight-API-Key": "alice"}
        assert (
            client.post(
                "/providers",
                headers=headers,
                json={"provider_id": "main", "name": "Main", "type": "openai"},
            ).status_code
            == 201
        )
        body = {
            "provider_id": "main",
            "request": edit_request(
                images=[png_input(number) for number in range(16)]
            ).model_dump(mode="json"),
        }
        assert client.post("/images/edits", json=body).status_code == 401
        response = client.post("/images/edits", headers=headers, json=body)
        assert response.status_code == (200 if allowed else 403)
        assert len(provider.requests) == (1 if allowed else 0)
        if allowed:
            assert response.headers["Cache-Control"] == "no-store"
            record_id = response.json()["record_id"]
            detail = client.get(f"/images/records/{record_id}", headers=headers).json()
            assert detail["request"]["images"] == body["request"]["images"]
            assert detail["owner_id"] == "alice"
            assert (
                "base64_data" not in client.get("/images/records", headers=headers).text
            )
            other = {"X-Evernight-API-Key": "bob"}
            assert (
                client.get(f"/images/records/{record_id}", headers=other).status_code
                == 404
            )
            assert (
                client.delete(f"/images/records/{record_id}", headers=other).status_code
                == 404
            )
        body["request"]["images"][3]["mime_type"] = "image/jpeg"
        invalid = client.post("/images/edits", headers=headers, json=body)
        assert invalid.status_code == 400
        assert PNG not in invalid.text
        assert len(provider.requests) == (1 if allowed else 0)
        del body["request"]["images"]
        assert (
            client.post("/images/edits", headers=headers, json=body).status_code == 400
        )


def test_edit_original_and_parameters_survive_sqlite_restart(tmp_path: Path) -> None:
    path = tmp_path / "images.sqlite3"
    provider = EditProvider()
    response = asyncio.run(provider.edit_images(edit_request()))
    record = ImageGenerationRecord(
        provider_id="main",
        request=edit_request(images=[png_input(number) for number in range(16)]),
        response=response,
    )
    store = SQLiteImageGenerationStore(path)
    store.save(record)
    store.close()
    restored = SQLiteImageGenerationStore(path)
    try:
        saved = restored.get(record.record_id)
        assert isinstance(saved.request, ImageEditRequest)
        assert saved.request.images == [png_input(number) for number in range(16)]
        assert saved.request.prompt == "Make the leaf blue"
    finally:
        restored.close()
