from typing import Annotated

from fastapi import APIRouter, Body, Response, status

from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderConfigUpdate,
    ProviderConfigView,
    ProviderInfo,
    ProviderModelCapability,
    ProviderModelConfig,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.template import PROVIDER_CONFIG_EXAMPLES


router = APIRouter(prefix="/providers", tags=["providers"])


@router.post(
    "",
    response_model=ProviderInfo,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="Register a provider configuration",
    description=(
        "Register provider configuration and create an instance if enabled. "
        "Disabled configurations remain manageable without resolving credentials. "
        "Use an enabled provider's `provider_id` in chat, session, and agent requests."
    ),
    operation_id="create_provider",
)
async def create_provider(
    config: Annotated[
        ProviderConfig,
        Body(openapi_examples=PROVIDER_CONFIG_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> ProviderInfo:
    return await interface.providers.create_provider(config)


@router.get(
    "",
    response_model=list[ProviderInfo],
    response_model_exclude_none=True,
    summary="List registered providers",
    description="Return provider configurations registered in the runtime without secrets.",
    operation_id="list_providers",
)
async def list_providers(interface: InterfaceDependency) -> list[ProviderInfo]:
    return await interface.providers.list_providers()


@router.get(
    "/{provider_id}/config",
    response_model=ProviderConfigView,
    summary="Get editable provider configuration without the API key",
    operation_id="get_provider_config",
)
async def get_provider_config(
    provider_id: str, interface: InterfaceDependency,
) -> ProviderConfigView:
    return await interface.providers.get_provider_config(provider_id)


@router.patch(
    "/{provider_id}",
    response_model=ProviderInfo,
    response_model_exclude_none=True,
    summary="Update provider configuration",
    description=(
        "Update only supplied fields while preserving the provider ID. Omitted "
        "credentials are retained; null clears the specified credential. A new "
        "API key or secret reference replaces the other credential source. Model "
        "and metadata maps replace their entire current values. Active calls "
        "finish on the previous instance. Setting is_enabled=false blocks new "
        "model calls and retains the configuration; enabling builds an instance "
        "before publishing the change. Raw API keys remain runtime-only."
    ),
    operation_id="update_provider",
)
async def update_provider(
    provider_id: str, update: ProviderConfigUpdate, interface: InterfaceDependency,
) -> ProviderInfo:
    return await interface.providers.update_provider(provider_id, update)


@router.get(
    "/{provider_id}/models",
    response_model=list[ProviderModelConfig],
    response_model_exclude_none=True,
    summary="List provider models",
    description=(
        "Ask the provider instance for models. By default this returns locally "
        "declared models. If the provider was configured with `discover_models`, "
        "the instance also asks the upstream models endpoint and falls back to "
        "declared models when discovery is unavailable. Disabled providers return "
        "only locally declared models without contacting the upstream service."
    ),
    operation_id="list_provider_models",
)
async def list_provider_models(
    provider_id: str,
    interface: InterfaceDependency,
) -> list[ProviderModelConfig]:
    return await interface.providers.list_provider_models(provider_id)


@router.get(
    "/{provider_id}/models/{model_id}",
    response_model=ProviderModelConfig,
    response_model_exclude_none=True,
    summary="Get one declared provider model",
    operation_id="get_provider_model",
)
async def get_provider_model(
    provider_id: str,
    model_id: str,
    interface: InterfaceDependency,
) -> ProviderModelConfig:
    return await interface.providers.get_provider_model(provider_id, model_id)


@router.get(
    "/{provider_id}/supports",
    response_model=bool,
    response_model_exclude_none=True,
    summary="Check provider capability",
    description="Check whether the provider has a declared model with this capability.",
    operation_id="provider_supports",
)
async def provider_supports(
    provider_id: str,
    capability: ProviderModelCapability,
    interface: InterfaceDependency,
) -> bool:
    return await interface.providers.provider_supports(provider_id, capability)


@router.post(
    "/{provider_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a provider",
    operation_id="delete_provider",
)
async def delete_provider(
    provider_id: str,
    interface: InterfaceDependency,
) -> None:
    await interface.providers.delete_provider(provider_id)
