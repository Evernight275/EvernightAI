from EvernightAI.core.protocol.interface import ProviderInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderInfo,
    ProviderModelCapability,
    ProviderModelConfig,
)


class ProviderApplication(ProviderInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def create_provider(self, config: ProviderConfig) -> ProviderInfo:
        await self._runtime.providers.create(config)
        return await self._runtime.providers.get_info(config.provider_id)

    async def list_providers(self) -> list[ProviderInfo]:
        return await self._runtime.providers.list_infos()

    async def list_provider_models(
        self,
        provider_id: str,
    ) -> list[ProviderModelConfig]:
        return await self._runtime.providers.list_models(provider_id)

    async def get_provider_model(
        self,
        provider_id: str,
        model_id: str,
    ) -> ProviderModelConfig:
        return await self._runtime.providers.get_model(provider_id, model_id)

    async def provider_supports(
        self,
        provider_id: str,
        capability: ProviderModelCapability,
    ) -> bool:
        return await self._runtime.providers.supports(provider_id, capability)

    async def delete_provider(self, provider_id: str) -> None:
        await self._runtime.providers.delete(provider_id)
