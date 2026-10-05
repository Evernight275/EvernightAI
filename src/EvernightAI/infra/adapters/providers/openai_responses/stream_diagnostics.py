import json
from typing import Any

from EvernightAI.core.error.provider import ProviderResponseError
from EvernightAI.infra.adapters.provider_usage import token_count


class ResponsesStreamDiagnostics:
    def __init__(self) -> None:
        self.event_counts: dict[str, int] = {}
        self.last_event: str | None = None
        self.final_event: str | None = None
        self.status: str | None = None
        self.incomplete_reason: str | None = None
        self.output_types: list[str] = []
        self.output_tokens: int | None = None
        self.reasoning_tokens: int | None = None
        self.max_output_tokens: int | None = None

    def observe(self, payload: dict[str, Any]) -> None:
        event_type = payload.get("type")
        event_type = event_type[:128] if isinstance(event_type, str) else "unknown"
        count_key = event_type
        if event_type not in self.event_counts and len(self.event_counts) >= 64:
            count_key = "other"
        self.event_counts[count_key] = self.event_counts.get(count_key, 0) + 1
        self.last_event = event_type
        if event_type not in {"response.completed", "response.incomplete"}:
            return
        self.final_event = event_type
        response = payload.get("response")
        if not isinstance(response, dict):
            return
        self.status = _label(response.get("status"))
        self.max_output_tokens = token_count(response.get("max_output_tokens"))
        details = response.get("incomplete_details")
        if isinstance(details, dict):
            self.incomplete_reason = _label(details.get("reason"))
        output = response.get("output")
        if isinstance(output, list):
            self.output_types = list(
                dict.fromkeys(
                    kind
                    for item in output
                    if isinstance(item, dict)
                    if (kind := _label(item.get("type"))) is not None
                )
            )[:64]
        usage = response.get("usage")
        if isinstance(usage, dict):
            self.output_tokens = token_count(usage.get("output_tokens"))
            output_details = usage.get("output_tokens_details")
            if isinstance(output_details, dict):
                self.reasoning_tokens = token_count(
                    output_details.get("reasoning_tokens")
                )

    def empty_output_error(self) -> ProviderResponseError:
        reason = "upstream returned empty or whitespace-only output"
        if self.final_event is None:
            reason = "stream ended before a final response event"
            if self.last_event is not None:
                reason += f" (last event: {self.last_event})"
        elif self.final_event == "response.incomplete" or self.status == "incomplete":
            reason = "response was incomplete"
            if self.incomplete_reason is not None:
                reason += f" ({self.incomplete_reason})"
        elif self.output_types == ["reasoning"]:
            reason = "upstream returned reasoning only, without an assistant answer"
        return ProviderResponseError(
            "OpenAI Responses stream ended without text or tool calls: " + reason,
            detail=json.dumps(
                {
                    "event_counts": self.event_counts,
                    "last_event": self.last_event,
                    "final_event": self.final_event,
                    "status": self.status,
                    "incomplete_reason": self.incomplete_reason,
                    "output_types": self.output_types,
                    "output_tokens": self.output_tokens,
                    "reasoning_tokens": self.reasoning_tokens,
                    "max_output_tokens": self.max_output_tokens,
                },
                ensure_ascii=False,
            ),
        )


def _label(value: object) -> str | None:
    return value[:128] if isinstance(value, str) and value else None
