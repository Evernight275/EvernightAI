from collections.abc import Awaitable, Callable

from EvernightAI.core.error.provider import ProviderNotFoundError
from EvernightAI.core.schema.provider import ProviderModelConfig


ModelDiscovery = Callable[[], Awaitable[list[ProviderModelConfig]]]


async def discover_models_or_declared(
    declared_models: dict[str, ProviderModelConfig],
    discover: ModelDiscovery,
    *,
    discover_models: bool = False,
) -> list[ProviderModelConfig]:
    if not discover_models:
        return list(declared_models.values())

    try:
        remote_models = await discover()
    except Exception:
        return list(declared_models.values())

    return merge_models(declared_models, remote_models)


def merge_models(
    declared_models: dict[str, ProviderModelConfig],
    remote_models: list[ProviderModelConfig],
) -> list[ProviderModelConfig]:
    models = dict(declared_models)
    for model in remote_models:
        models.setdefault(model.model_id, model)

    return list(models.values())


async def get_discovered_model_or_declared(
    model_id: str,
    declared_models: dict[str, ProviderModelConfig],
    discover: ModelDiscovery,
    *,
    discover_models: bool = False,
) -> ProviderModelConfig:
    for model in await discover_models_or_declared(
        declared_models,
        discover,
        discover_models=discover_models,
    ):
        if model.model_id == model_id:
            return model

    raise ProviderNotFoundError(f"The model {model_id} is not found")
