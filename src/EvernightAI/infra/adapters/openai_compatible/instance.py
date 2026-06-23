from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from openai import AsyncOpenAI, OpenAIError
from openai.types.chat import ChatCompletionChunk

from EvernightAI.core.error.provider import ProviderNotFoundError
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import ChatRequest, ChatResponse
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
)
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.infra.adapters.openai_compatible.errors import (
    raise_openai_compatible_error,
)
from EvernightAI.infra.adapters.openai_compatible.mapper import (
    OpenAIChatStreamNormalizer,
    from_openai_chat_completion,
    to_openai_messages,
    to_openai_tools,
)


class OpenAICompatibleProviderInstance(ProviderInstanceProtocol):
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
            "messages": to_openai_messages(request.messages),
            "timeout": model.timeout.total_seconds(),
        }

        if request.tools:
            params["tools"] = to_openai_tools(request.tools)

        try:
            response = await self._client.chat.completions.create(**params)
        except OpenAIError as error:
            raise_openai_compatible_error(error)

        return from_openai_chat_completion(response)

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        model = self._model_for_request(request.model_id)
        params: dict[str, Any] = {
            "model": model.model_id,
            "messages": to_openai_messages(request.messages),
            "timeout": model.timeout.total_seconds(),
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if request.tools:
            params["tools"] = to_openai_tools(request.tools)

        try:
            stream = await self._client.chat.completions.create(**params)
        except OpenAIError as error:
            raise_openai_compatible_error(error)

        return OpenAICompatibleChatStream(stream)

    async def list_models(self) -> list[ProviderModelConfig]:
        return list(self._models.values())

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        if model_id in self._models:
            return self._models[model_id]

        raise ProviderNotFoundError(f"The model {model_id} is not found")

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return any(capability in model.capabilities for model in self._models.values())

    async def close(self) -> None:
        await self._client.close()
        self._closed = True

    def _model_for_request(self, model_id: str) -> ProviderModelConfig:
        return self._models.get(model_id) or ProviderModelConfig(model_id=model_id)


class OpenAICompatibleChatStream:
    def __init__(self, stream: AsyncIterable[ChatCompletionChunk]) -> None:
        self._stream = stream
        self._normalizer = OpenAIChatStreamNormalizer()

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ChatStreamEvent]:
        try:
            async for chunk in self._stream:
                for event in self._normalizer.map_chunk(chunk):
                    yield event
        except OpenAIError as error:
            raise_openai_compatible_error(error)

        yield ChatStreamEvent(event_type=ChatStreamEventType.DONE)
