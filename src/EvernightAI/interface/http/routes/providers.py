from fastapi import APIRouter, status

from EvernightAI.core.schema.provider import ProviderConfig, ProviderInfo
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
    await interface.chat.create_provider(config)
    return ProviderInfo(
        provider_id=config.provider_id,
        name=config.name,
        type=config.type,
        is_enabled=config.is_enabled,
        model=config.model,
        metadata=dict(config.metadata),
    )
