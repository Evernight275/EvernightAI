from typing import Any


REASONING_EFFORT_METADATA_KEY = "reasoning_effort"
REASONING_EFFORT_VALUES = {"low", "medium", "high"}


def provider_request_params_from_metadata(
    metadata: dict[str, Any],
) -> dict[str, Any]:
    reasoning_effort = metadata.get(REASONING_EFFORT_METADATA_KEY)
    if reasoning_effort not in REASONING_EFFORT_VALUES:
        return {}

    return {REASONING_EFFORT_METADATA_KEY: reasoning_effort}
