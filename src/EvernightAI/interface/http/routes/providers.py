from fastapi import APIRouter, Response, status

from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderInfo,
    ProviderModelCapability,
    ProviderModelConfig,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency


router = APIRouter(prefix="/providers", tags=["providers"])


@router.post(
    "",
    response_model=ProviderInfo,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(
    config: ProviderConfig,
    interface: InterfaceDependency,
) -> ProviderInfo:
    return await interface.providers.create_provider(config)


@router.get("/{provider_id}/models", response_model=list[ProviderModelConfig])
async def list_provider_models(
    provider_id: str,
    interface: InterfaceDependency,
) -> list[ProviderModelConfig]:
    return await interface.providers.list_provider_models(provider_id)


@router.get("/{provider_id}/models/{model_id}", response_model=ProviderModelConfig)
async def get_provider_model(
    provider_id: str,
    model_id: str,
    interface: InterfaceDependency,
) -> ProviderModelConfig:
    return await interface.providers.get_provider_model(provider_id, model_id)


@router.get("/{provider_id}/supports", response_model=bool)
async def provider_supports(
    provider_id: str,
    capability: ProviderModelCapability,
    interface: InterfaceDependency,
) -> bool:
    return await interface.providers.provider_supports(provider_id, capability)


@router.delete(
    "/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_provider(
    provider_id: str,
    interface: InterfaceDependency,
) -> None:
    await interface.providers.delete_provider(provider_id)
