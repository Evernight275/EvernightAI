from hashlib import sha256
import json

from EvernightAI.core.schema.content import ChatRequest, PromptCacheMode
from EvernightAI.core.schema.provider import ProviderConfig


def openai_prompt_cache_params(
    provider: ProviderConfig,
    request: ChatRequest,
) -> dict[str, str]:
    policy = request.prompt_cache
    if (
        policy is None
        or policy.mode is not PromptCacheMode.PREFER_EXPLICIT
        or policy.scope_id is None
    ):
        return {}

    identity = json.dumps(
        [provider.provider_id, request.model_id, policy.scope_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return {"prompt_cache_key": sha256(identity).hexdigest()}
