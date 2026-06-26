from collections.abc import AsyncIterator
from typing import Any

import httpx

from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import ChatRequest, ChatResponse
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
)
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.infra.adapters.gemini.mapper import (
    from_gemini_response,
    from_gemini_stream_chunk,
    to_gemini_request,
)
from EvernightAI.infra.adapters.http_errors import raise_httpx_provider_error
from EvernightAI.infra.adapters.model_discovery import (
    discover_models_or_declared,
    get_discovered_model_or_declared,
)
from EvernightAI.infra.adapters.provider_metadata import timeout_seconds_from_metadata


class GeminiProviderInstance(ProviderInstanceProtocol):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._models = dict(config.model)
        self._closed = False
        self._client = httpx.AsyncClient(
            base_url=config.base_url or "https://generativelanguage.googleapis.com",
            headers={"x-goog-api-key": config.api_key or ""},
        )

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = self._model_for_request(request.model_id)
        payload = to_gemini_request(request.messages)

        try:
            response = await self._client.post(
                f"/v1beta/models/{model.model_id}:generateContent",
                json=payload,
                timeout=timeout_seconds_from_metadata(request.metadata)
                or model.timeout.total_seconds(),
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise_httpx_provider_error(error)

        return from_gemini_response(response.json(), model.model_id)

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        model = self._model_for_request(request.model_id)
        payload = to_gemini_request(request.messages)
        return GeminiChatStream(
            self._client,
            f"/v1beta/models/{model.model_id}:streamGenerateContent",
            payload,
            timeout_seconds_from_metadata(request.metadata)
            or model.timeout.total_seconds(),
        )

    async def list_models(self) -> list[ProviderModelConfig]:
        return await discover_models_or_declared(self._models, self._list_remote_models)

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return await get_discovered_model_or_declared(
            model_id,
            self._models,
            self._list_remote_models,
        )

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return any(capability in model.capabilities for model in self._models.values())

    async def close(self) -> None:
        await self._client.aclose()
        self._closed = True

    def _model_for_request(self, model_id: str) -> ProviderModelConfig:
        return self._models.get(model_id) or ProviderModelConfig(model_id=model_id)

    async def _list_remote_models(self) -> list[ProviderModelConfig]:
        response = await self._client.get("/v1beta/models")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return []

        models = payload.get("models")
        if not isinstance(models, list):
            return []

        discovered: list[ProviderModelConfig] = []
        for model in models:
            if not isinstance(model, dict):
                continue
            model_id = model.get("name")
            if not isinstance(model_id, str) or not model_id:
                continue
            discovered.append(
                ProviderModelConfig(model_id=model_id.removeprefix("models/"))
            )

        return discovered


class GeminiChatStream:
    def __init__(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: dict[str, Any],
        timeout: float,
    ) -> None:
        self._client = client
        self._url = url
        self._payload = payload
        self._timeout = timeout

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ChatStreamEvent]:
        try:
            async with self._client.stream(
                "POST",
                self._url,
                params={"alt": "sse"},
                json=self._payload,
                timeout=self._timeout,
            ) as response:
                response.raise_for_status()
                async for chunk in _iter_sse_json(response):
                    for event in from_gemini_stream_chunk(chunk):
                        yield event
        except httpx.HTTPError as error:
            raise_httpx_provider_error(error)

        yield ChatStreamEvent(event_type=ChatStreamEventType.DONE)


async def _iter_sse_json(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    async for line in response.aiter_lines():
        line = line.strip()
        if not line.startswith("data:"):
            continue

        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue

        parsed = httpx.Response(200, content=data).json()
        if isinstance(parsed, dict):
            yield parsed
