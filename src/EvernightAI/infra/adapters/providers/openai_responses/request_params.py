from typing import Any

from EvernightAI.infra.adapters.provider_metadata import (
    provider_request_params_from_metadata,
)


def responses_request_params_from_metadata(
    metadata: dict[str, Any],
) -> dict[str, Any]:
    params = provider_request_params_from_metadata(metadata)
    effort = params.pop("reasoning_effort", None)
    if effort is not None:
        params["reasoning"] = {"effort": effort}
    return params
