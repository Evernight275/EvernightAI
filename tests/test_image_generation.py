import asyncio
import base64
import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from openai.types.images_response import ImagesResponse
from pydantic import ValidationError

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.error.provider import (
    ProviderCapabilityUnsupportedError,
    ProviderDisabledError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.image import (
    GeneratedImage,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderConfigUpdate,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.infra.adapters.providers.openai_compatible.images import (
    from_openai_images,
    image_generation_params,
)
from EvernightAI.infra.adapters.providers.openai_compatible.instance import (
    OpenAICompatibleProviderInstance,
)
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import ApiKeyHttpAuthDevice
from EvernightAI.interface.http.schema import HttpApiKeyCredential
from tests.test_interface_http import make_runtime
from tests.test_provider_domain import FakeProvider


PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nimage").decode()


def request(**kwargs: Any) -> ImageGenerationRequest:
    return ImageGenerationRequest(
        model_id="image-model", prompt="A green leaf", **kwargs
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"count": True},
        {"count": 0},
        {"count": 11},
        {"prompt": " "},
        {"timeout_seconds": 0},
        {"model_id": " "},
        {"output_format": "svg"},
        {"unknown": 1},
    ],
)
def test_image_request_rejects_invalid_inputs(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ImageGenerationRequest.model_validate(
            {"model_id": "image-model", "prompt": "Leaf", **changes}
        )


def test_gpt_image_base64_intent_omits_unsupported_response_format() -> None:
    params = image_generation_params(
        ImageGenerationRequest(
            model_id="gpt-image-1", prompt="Leaf", result_format="base64"
        )
    )
    assert "response_format" not in params
    with pytest.raises(ProviderRequestError):
        image_generation_params(
            ImageGenerationRequest(
                model_id="gpt-image-1", prompt="Leaf", result_format="url"
            )
        )


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"RIFFxxxxWEBP", "image/webp"),
    ],
)
def test_image_mapper_detects_actual_format(data: bytes, mime: str) -> None:
    response = ImagesResponse.model_validate(
        {
            "created": 123,
            "data": [
                {
                    "b64_json": base64.b64encode(data).decode(),
                    "revised_prompt": "Revised leaf",
                }
            ],
        }
    )
    result = from_openai_images(response, request(output_format="jpeg"))
    assert result.images[0].mime_type == mime
    assert result.images[0].revised_prompt == "Revised leaf"
    assert result.usage is None


@pytest.mark.parametrize(
    "data",
    [
        [],
        [{}],
        [{"url": "javascript:alert(1)"}],
        [{"b64_json": "!!"}],
        [{"b64_json": base64.b64encode(b"<svg />").decode()}],
    ],
)
def test_image_mapper_translates_invalid_outputs(data: list[dict[str, Any]]) -> None:
    with pytest.raises(ProviderResponseError):
        from_openai_images(
            ImagesResponse.model_validate({"created": 123, "data": data}), request()
        )


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": -1, "output_tokens": True, "total_tokens": "invalid"},
        "invalid",
        {"input_tokens": 0, "output_tokens": 5, "total_tokens": 5},
    ],
)
def test_image_mapper_preserves_raw_usage_without_failing(usage: Any) -> None:
    response = ImagesResponse.model_construct(
        created=123,
        data=ImagesResponse.model_validate(
            {"created": 123, "data": [{"url": "https://images.example/leaf.png"}]}
        ).data,
        usage=usage,
    )
    result = from_openai_images(response, request())
    assert result.usage is not None
    raw = result.usage.metadata["provider_usage"]
    if isinstance(usage, dict):
        assert all(raw[key] == value for key, value in usage.items())
    else:
        assert raw == usage
    assert result.usage.input_tokens == (
        0 if isinstance(usage, dict) and usage.get("input_tokens") == 0 else None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [True, False])
async def test_images_call_sdk_without_discovery_and_forward_parameters(
    declared: bool,
) -> None:
    calls: list[httpx.Request] = []

    def respond(call: httpx.Request) -> httpx.Response:
        calls.append(call)
        return httpx.Response(200, json={"created": 123, "data": [{"b64_json": PNG}]})

    model = ProviderModelConfig(
        model_id="image-model",
        timeout=timedelta(seconds=75),
        capabilities=[ProviderModelCapability.IMAGE_GENERATION],
    )
    instance = OpenAICompatibleProviderInstance(
        ProviderConfig(
            provider_id="main",
            name="Main",
            type=ProviderType.OPENAI,
            model={"image": model} if declared else {},
        )
    )
    await instance._client.close()
    instance._client = AsyncOpenAI(
        api_key="test",
        base_url="https://provider.example/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        result = await instance.generate_images(
            request(
                count=2,
                size="1024x1024",
                quality="high",
                output_format="png",
                background="transparent",
                result_format="base64",
            )
        )
        assert result.images[0].mime_type == "image/png"
        assert len(calls) == 1
        assert calls[0].url.path == "/v1/images/generations"
        assert json.loads(calls[0].content) == {
            "model": "image-model",
            "prompt": "A green leaf",
            "n": 2,
            "size": "1024x1024",
            "quality": "high",
            "output_format": "png",
            "background": "transparent",
            "response_format": "b64_json",
        }
        assert calls[0].extensions["timeout"]["read"] == (75 if declared else 180)
        await instance.generate_images(request(timeout_seconds=42))
        assert calls[-1].extensions["timeout"]["read"] == 42
    finally:
        await instance.close()


@pytest.mark.asyncio
async def test_image_sdk_connection_error_is_translated_without_retry() -> None:
    calls = 0

    def fail(call: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=call)

    instance = OpenAICompatibleProviderInstance(
        ProviderConfig(provider_id="main", name="Main", type=ProviderType.OPENAI)
    )
    await instance._client.close()
    instance._client = AsyncOpenAI(
        api_key="test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(fail)),
    )
    try:
        with pytest.raises(ProviderUnavailableError):
            await instance.generate_images(request())
        assert calls == 1
    finally:
        await instance.close()


class ImageProvider(FakeProvider):
    def __init__(self, *, blocked: bool = False) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.requests: list[ImageGenerationRequest] = []
        if not blocked:
            self.release.set()

    async def generate_images(
        self, request: ImageGenerationRequest
    ) -> ImageGenerationResponse:
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        return ImageGenerationResponse(
            model_id=request.model_id,
            images=[GeneratedImage(base64_data=PNG, mime_type="image/png")],
        )


@pytest.mark.asyncio
async def test_image_generation_lifecycle_with_hot_update_and_cancellation() -> None:
    instances: list[ImageProvider] = []

    async def build(_config: ProviderConfig) -> ImageProvider:
        instance = ImageProvider(blocked=True)
        instances.append(instance)
        return instance

    factory = ProviderFactory()
    factory.register(ProviderType.OPENAI, build)
    manager = ProviderManager(factory)
    await manager.create(
        ProviderConfig(provider_id="main", name="Main", type=ProviderType.OPENAI)
    )
    task = asyncio.create_task(manager.generate_images("main", request()))
    await asyncio.wait_for(instances[0].started.wait(), 2)
    await manager.update("main", ProviderConfigUpdate(name="Updated"))
    assert not instances[0].closed
    instances[0].release.set()
    assert (await task).model_id == "image-model"
    assert instances[0].closed
    task = asyncio.create_task(manager.generate_images("main", request()))
    await asyncio.wait_for(instances[1].started.wait(), 2)
    await manager.update("main", ProviderConfigUpdate(is_enabled=False))
    assert not instances[1].closed
    with pytest.raises(ProviderDisabledError):
        await manager.generate_images("main", request())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert instances[1].closed
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("image_adapter", [True, False])
async def test_manager_rejects_unsupported_model_or_adapter(
    image_adapter: bool,
) -> None:
    async def build(_config: ProviderConfig) -> FakeProvider:
        return ImageProvider() if image_adapter else FakeProvider()

    factory = ProviderFactory()
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
            if image_adapter
            else {},
        )
    )
    try:
        with pytest.raises(ProviderCapabilityUnsupportedError):
            await manager.generate_images("main", request())
    finally:
        await manager.close()


@pytest.mark.parametrize("allowed", [True, False])
def test_http_image_generation_checks_permission_before_dispatch(allowed: bool) -> None:
    provider = ImageProvider()
    runtime = make_runtime(provider=provider)
    app = create_http_app(
        create_interface(runtime),
        auth_device=ApiKeyHttpAuthDevice(
            [
                HttpApiKeyCredential(
                    api_key="test",
                    principal=Principal(
                        principal_id="user",
                        permissions=["providers:create"]
                        + (["images:generate"] if allowed else []),
                    ),
                )
            ]
        ),
        authorized_interface_factory=lambda interface, principal: (
            AuthorizedEvernightInterface(
                interface, Authorizer(PermissionAuthPolicy()), principal
            )
        ),
    )
    with TestClient(app) as client:
        headers = {"X-Evernight-API-Key": "test"}
        assert (
            client.post(
                "/providers",
                headers=headers,
                json={"provider_id": "main", "name": "Main", "type": "openai"},
            ).status_code
            == 201
        )
        body = {"provider_id": "main", "request": request().model_dump(mode="json")}
        assert client.post("/images/generations", json=body).status_code == 401
        response = client.post("/images/generations", headers=headers, json=body)
        assert response.status_code == (200 if allowed else 403)
        assert len(provider.requests) == (1 if allowed else 0)
        if allowed:
            assert response.headers["Cache-Control"] == "no-store"
            assert response.json()["images"][0]["base64_data"] == PNG
        body["request"]["count"] = 0
        assert (
            client.post("/images/generations", headers=headers, json=body).status_code
            == 400
        )
