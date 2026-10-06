import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from EvernightAI.core.error.provider import ProviderResponseError


async def iter_sse_json(
    response: httpx.Response,
) -> AsyncIterator[tuple[str | None, dict[str, Any]]]:
    event: str | None = None
    data: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data:
                parsed = _parse_data(data)
                if parsed is not None:
                    yield event, parsed
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].lstrip(" ")
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if data:
        parsed = _parse_data(data)
        if parsed is not None:
            yield event, parsed


def _parse_data(lines: list[str]) -> dict[str, Any] | None:
    data = "\n".join(lines)
    if not data or data == "[DONE]":
        return None
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as error:
        raise ProviderResponseError("Provider stream contains invalid JSON") from error
    if not isinstance(parsed, dict):
        raise ProviderResponseError("Provider stream data must be a JSON object")
    return parsed
