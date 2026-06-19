from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.stream import SSEProtocol
from EvernightAI.core.schema.content import ChatRequest, ChatResponse
from EvernightAI.core.schema.provider import ProviderConfig


class ChatApplication:
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def create_provider(
        self,
        config: ProviderConfig,
    ) -> ProviderInstanceProtocol:
        return await self._runtime.providers.create(config)

    async def chat(self, provider_id: str, request: ChatRequest) -> ChatResponse:
        return await self._runtime.providers.chat(provider_id, request)

    async def chat_stream(self, provider_id: str, request: ChatRequest) -> SSEProtocol:
        return await self._runtime.providers.chat_stream(provider_id, request)

    async def close(self) -> None:
        await self._runtime.close()
