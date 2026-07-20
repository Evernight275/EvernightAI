from typing import Any

from EvernightAI.core.schema.content import ChatRequest, PromptCacheMode


def anthropic_prompt_cache_params(request: ChatRequest) -> dict[str, Any]:
    policy = request.prompt_cache
    if policy is None or policy.mode is not PromptCacheMode.PREFER_EXPLICIT:
        return {}

    return {"cache_control": {"type": "ephemeral"}}
