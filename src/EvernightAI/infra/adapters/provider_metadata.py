from typing import Any

from EvernightAI.core.error.chat import ChatInputError


REASONING_EFFORT_METADATA_KEY = "reasoning_effort"
REASONING_EFFORT_VALUES = {"low", "medium", "high"}
TIMEOUT_SECONDS_METADATA_KEY = "timeout_seconds"


def max_output_tokens_from_metadata(*sources: dict[str, Any]) -> int | None:
    for metadata in sources:
        if "max_output_tokens" not in metadata:
            continue
        value = metadata["max_output_tokens"]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ChatInputError("max_output_tokens must be a positive integer")
        return value
    return None


def provider_request_params_from_metadata(
    metadata: dict[str, Any],
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    reasoning_effort = metadata.get(REASONING_EFFORT_METADATA_KEY)
    if reasoning_effort in REASONING_EFFORT_VALUES:
        params[REASONING_EFFORT_METADATA_KEY] = reasoning_effort

    timeout_seconds = timeout_seconds_from_metadata(metadata)
    if timeout_seconds is not None:
        params["timeout"] = timeout_seconds

    return params


def timeout_seconds_from_metadata(metadata: dict[str, Any]) -> float | None:
    value = metadata.get(TIMEOUT_SECONDS_METADATA_KEY)
    if not isinstance(value, int | float):
        return None
    if value <= 0:
        return None

    return float(value)
