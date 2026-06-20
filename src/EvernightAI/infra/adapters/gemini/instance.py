from collections.abc import AsyncIterator
from typing import Any

import httpx

from EvernightAI.core.error.provider import ProviderNotFoundError
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import SSEProtocol
from EvernightAI.core.schema.content import ChatRequest, ChatResponse
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
)
from EvernightAI.core.schema.stream import SSEEvent
from EvernightAI.infra.adapters.gemini.mapper import (
    from_gemini_response,
    from_gemini_stream_chunk,
    to_gemini_request,
)
from EvernightAI.infra.adapters.http_errors import raise_httpx_provider_error


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
                timeout=model.timeout.total_seconds(),
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise_httpx_provider_error(error)

        return from_gemini_response(response.json(), model.model_id)

    async def chat_stream(self, request: ChatRequest) -> SSEProtocol:
        model = self._model_for_request(request.model_id)
        payload = to_gemini_request(request.messages)

        try:
            response = await self._client.post(
                f"/v1beta/models/{model.model_id}:streamGenerateContent",
                params={"alt": "sse"},
                json=payload,
                timeout=model.timeout.total_seconds(),
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise_httpx_provider_error(error)

        return GeminiSSEStream(response.text)

    async def list_models(self) -> list[ProviderModelConfig]:
        return list(self._models.values())

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        if model_id in self._models:
            return self._models[model_id]

        raise ProviderNotFoundError(f"The model {model_id} is not found")

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return any(capability in model.capabilities for model in self._models.values())

    async def close(self) -> None:
        await self._client.aclose()
        self._closed = True

    def _model_for_request(self, model_id: str) -> ProviderModelConfig:
        return self._models.get(model_id) or ProviderModelConfig(model_id=model_id)


class GeminiSSEStream:
    def __init__(self, text: str) -> None:
        self._text = text

    def __aiter__(self) -> AsyncIterator[SSEEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[SSEEvent]:
        for chunk in _iter_sse_json(self._text):
            yield from_gemini_stream_chunk(chunk)

        yield SSEEvent(data="[DONE]", event="done")


def _iter_sse_json(text: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue

        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue

        parsed = httpx.Response(200, content=data).json()
        if isinstance(parsed, dict):
            chunks.append(parsed)

    return chunks
