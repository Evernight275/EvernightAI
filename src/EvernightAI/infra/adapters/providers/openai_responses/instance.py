from collections.abc import AsyncIterable, AsyncIterator
from typing import Any, cast

from openai import AsyncOpenAI, OpenAIError
from openai.types.responses import ResponseStreamEvent

from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import ChatRequest, ChatResponse
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
)
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.infra.adapters.providers.openai_compatible.errors import (
    raise_openai_compatible_error,
)
from EvernightAI.infra.adapters.providers.openai_responses.mapper import (
    OpenAIResponsesStreamNormalizer,
    from_openai_response,
    to_openai_response_input,
    to_openai_response_tools,
)
from EvernightAI.infra.adapters.model_discovery import (
    discover_models_or_declared,
    get_discovered_model_or_declared,
)
from EvernightAI.infra.adapters.provider_metadata import (
    provider_request_params_from_metadata,
)


class OpenAIResponsesProviderInstance(ProviderInstanceProtocol):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._models = dict(config.model)
        self._closed = False
        self._client = AsyncOpenAI(
            api_key=config.api_key or "not-needed",
            base_url=config.base_url,
        )

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = self._model_for_request(request.model_id)
        params: dict[str, Any] = {
            "model": model.model_id,
            "input": to_openai_response_input(request.messages),
            "timeout": model.timeout.total_seconds(),
        }

        if request.tools:
            params["tools"] = to_openai_response_tools(request.tools)
        params.update(provider_request_params_from_metadata(request.metadata))

        try:
            response = await self._client.responses.create(**params)
        except OpenAIError as error:
            raise_openai_compatible_error(error)

        return from_openai_response(response)

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        model = self._model_for_request(request.model_id)
        params: dict[str, Any] = {
            "model": model.model_id,
            "input": to_openai_response_input(request.messages),
            "timeout": model.timeout.total_seconds(),
            "stream": True,
        }

        if request.tools:
            params["tools"] = to_openai_response_tools(request.tools)
        params.update(provider_request_params_from_metadata(request.metadata))

        try:
            stream = await self._client.responses.create(**params)
        except OpenAIError as error:
            raise_openai_compatible_error(error)

        return OpenAIResponsesChatStream(
            cast(AsyncIterable[ResponseStreamEvent], stream)
        )

    async def list_models(self) -> list[ProviderModelConfig]:
        return await discover_models_or_declared(
            self._models,
            self._list_remote_models,
            discover_models=self.config.discover_models,
        )

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return await get_discovered_model_or_declared(
            model_id,
            self._models,
            self._list_remote_models,
            discover_models=self.config.discover_models,
        )

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return any(capability in model.capabilities for model in self._models.values())

    async def close(self) -> None:
        await self._client.close()
        self._closed = True

    def _model_for_request(self, model_id: str) -> ProviderModelConfig:
        return self._models.get(model_id) or ProviderModelConfig(model_id=model_id)

    async def _list_remote_models(self) -> list[ProviderModelConfig]:
        page = await self._client.models.list()
        discovered: list[ProviderModelConfig] = []
        for model in page.data:
            model_id = getattr(model, "id", None)
            if isinstance(model_id, str) and model_id:
                discovered.append(ProviderModelConfig(model_id=model_id))

        return discovered


class OpenAIResponsesChatStream:
    def __init__(self, stream: AsyncIterable[ResponseStreamEvent]) -> None:
        self._stream = stream
        self._normalizer = OpenAIResponsesStreamNormalizer()

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ChatStreamEvent]:
        try:
            async for event in self._stream:
                yield self._normalizer.map_event(event)
        except OpenAIError as error:
            raise_openai_compatible_error(error)

        yield ChatStreamEvent(event_type=ChatStreamEventType.DONE)
