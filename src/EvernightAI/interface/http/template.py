from typing import cast

from fastapi.openapi.models import Example


API_DESCRIPTION = """
EvernightAI HTTP API exposes an assembled runtime for providers, chat, context,
memory, skills, tools, sessions, and agent runs.

Common first flow:

1. `POST /providers` to register a provider id such as `main`.
2. `POST /chat` for a one-off model call, or `POST /contexts` then
   `POST /chat/context` to persist conversation history.
3. Use `POST /sessions` and `POST /sessions/{session_id}/chat` when you want a
   product-style conversation object that owns its context/provider/model.
4. Use `POST /agent-runs` or `POST /agent-runs/stream` when a request may need
   tools, approvals, trace events, or multiple model/tool rounds.

Most request bodies below show the smallest useful JSON first. Optional fields
such as `skills`, `tools`, `memory_query`, and `metadata` are advanced controls.
Provider-specific controls belong in `request.metadata`; for example,
`reasoning_effort` accepts `low`, `medium`, or `high` for OpenAI-compatible
providers that support it.
"""


OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Readiness check.",
    },
    {
        "name": "providers",
        "description": "Register provider instances and inspect declared models.",
    },
    {
        "name": "chat",
        "description": "Direct chat calls and context-aware chat calls.",
    },
    {
        "name": "contexts",
        "description": "Persist model-visible conversation messages.",
    },
    {
        "name": "sessions",
        "description": "User-facing conversations that bind context, provider, and model.",
    },
    {
        "name": "agent-runs",
        "description": "Multi-step model runs with optional tools and approvals.",
    },
    {
        "name": "memories",
        "description": "Durable facts and preferences selected into future requests.",
    },
    {
        "name": "skills",
        "description": "Reusable prompt capabilities that can be rendered into chat.",
    },
    {
        "name": "tools",
        "description": "Registered external actions available to chat or agent flows.",
    },
]


def _text_message(text: str, *, role: str = "user") -> dict[str, object]:
    return {
        "role": role,
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ],
    }


def _tool_definition() -> dict[str, object]:
    return {
        "tool_name": "write_file",
        "description": "Write text to a workspace file.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        "requires_approval": True,
    }


def _openapi_examples(examples: dict[str, object]) -> dict[str, Example]:
    return cast(dict[str, Example], examples)


CHAT_RESPONSE_EXAMPLE = {
    "description": "Successful chat response.",
    "content": {
        "application/json": {
            "example": {
                "response_id": "resp-1",
                "model_id": "gpt-4.1-mini",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello."}],
                    "metadata": {},
                },
                "finish_reason": "stop",
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 20,
                    "total_tokens": 32,
                    "metadata": {},
                },
                "metadata": {},
            }
        }
    },
}


SESSION_CHAT_RESPONSE_EXAMPLE = {
    "description": "Successful session chat response.",
    "content": {
        "application/json": {
            "example": {
                "session": {
                    "session_id": "session-1",
                    "title": "Planning chat",
                    "context_id": "ctx-1",
                    "provider_id": "main",
                    "model_id": "gpt-4.1-mini",
                    "status": "active",
                    "metadata": {},
                },
                "response": CHAT_RESPONSE_EXAMPLE["content"]["application/json"][
                    "example"
                ],
            }
        }
    },
}


AGENT_RUN_STATE_RESPONSE_EXAMPLE = {
    "description": "Agent run state.",
    "content": {
        "application/json": {
            "example": {
                "run_id": "run-1",
                "request": {
                    "provider_id": "main",
                    "context_id": "ctx-1",
                    "model_id": "gpt-4.1-mini",
                    "messages": [_text_message("Answer and stop.")],
                    "max_tool_rounds": 0,
                    "recover_tool_errors": True,
                    "write_memory": False,
                    "tool_approvals": [],
                    "pause_on_approval": False,
                    "metadata": {"run_id": "run-1"},
                },
                "status": "finished",
                "remaining_tool_rounds": 0,
                "tool_rounds_used": 0,
                "pending_tool_calls": [],
                "pending_approval_requests": [],
                "metadata": {"run_id": "run-1"},
            }
        }
    },
}


CHAT_STREAM_ERROR_SSE_EXAMPLE = {
    "description": "SSE stream. Provider errors are emitted as `chat.error` events.",
    "content": {
        "text/event-stream": {
            "example": (
                "event: chat.error\n"
                'data: {"event_type":"error","error_type":"ProviderUnavailableError",'
                '"error_message":"provider unavailable",'
                '"metadata":{"detail":"status_code=503"}}\n\n'
            )
        }
    },
}


AGENT_TRACE_SSE_EXAMPLE = {
    "description": "SSE stream of agent trace events.",
    "content": {
        "text/event-stream": {
            "example": (
                "event: run_started\n"
                'data: {"event_type":"run_started","summary":"Agent run started"}\n\n'
                "event: run_stopped\n"
                'data: {"event_type":"run_stopped","summary":"Agent run stopped: finished",'
                '"metadata":{"reason":"finished"}}\n\n'
            )
        }
    },
}


PROVIDER_CONFIG_EXAMPLES = _openapi_examples({
    "openaiCompatible": {
        "summary": "OpenAI-compatible provider",
        "description": "Register a provider id that later chat requests can use.",
        "value": {
            "provider_id": "main",
            "name": "Main provider",
            "type": "openai",
            "api_key": "sk-...",
            "base_url": "https://api.openai.com/v1",
            "model": {
                "gpt-4.1-mini": {
                    "model_id": "gpt-4.1-mini",
                    "capabilities": ["chat"],
                }
            },
        },
    },
    "anthropic": {
        "summary": "Anthropic provider",
        "value": {
            "provider_id": "anthropic-main",
            "name": "Anthropic",
            "type": "anthropic",
            "api_key": "sk-ant-...",
            "model": {
                "claude-3-5-haiku-latest": {
                    "model_id": "claude-3-5-haiku-latest",
                    "capabilities": ["chat"],
                }
            },
        },
    },
})


DIRECT_CHAT_EXAMPLES = _openapi_examples({
    "minimal": {
        "summary": "Smallest one-off chat",
        "description": "Use this after registering provider id `main`.",
        "value": {
            "provider_id": "main",
            "request": {
                "model_id": "gpt-4.1-mini",
                "messages": [_text_message("Hello, give me a short answer.")],
            },
        },
    },
    "withMetadata": {
        "summary": "One-off chat with request metadata",
        "description": "Metadata is passed through for tracing; providers may ignore it.",
        "value": {
            "provider_id": "main",
            "request": {
                "model_id": "gpt-4.1-mini",
                "messages": [_text_message("Answer in one sentence.")],
                "metadata": {"request_id": "req-1"},
            },
        },
    },
    "withReasoningEffort": {
        "summary": "One-off chat with reasoning effort",
        "description": "OpenAI-compatible providers receive `reasoning_effort` as a provider request parameter.",
        "value": {
            "provider_id": "main",
            "request": {
                "model_id": "gpt-4.1-mini",
                "messages": [_text_message("Think carefully, then answer briefly.")],
                "metadata": {"reasoning_effort": "high"},
            },
        },
    },
    "withSkill": {
        "summary": "Chat with a skill prompt",
        "value": {
            "provider_id": "main",
            "request": {
                "model_id": "gpt-4.1-mini",
                "messages": [_text_message("Echo this request.")],
                "skills": [{"skill_name": "echo"}],
            },
        },
    },
})


CHAT_WITH_CONTEXT_EXAMPLES = _openapi_examples({
    "minimal": {
        "summary": "Smallest context chat",
        "description": "Create `ctx-1` first with `POST /contexts`.",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Continue from the stored context.")],
        },
    },
    "streamReady": {
        "summary": "Same body for `/chat/context/stream`",
        "description": "Use this exact body with the streaming endpoint.",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Stream the answer and save it.")],
            "metadata": {"request_id": "stream-1"},
        },
    },
    "withSessionMemory": {
        "summary": "Chat with selected session memory",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Use my saved preference.")],
            "memory_query": {
                "scope": "session",
                "scope_id": "session-1",
                "limit": 3,
            },
            "metadata": {"request_id": "req-1"},
        },
    },
    "withReasoningEffort": {
        "summary": "Context chat with reasoning effort",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Reason through this before answering.")],
            "metadata": {"reasoning_effort": "high"},
        },
    },
})


CONTEXT_EXAMPLES = _openapi_examples({
    "empty": {
        "summary": "Empty context",
        "description": "Create this first, then call `/chat/context`.",
        "value": {
            "context_id": "ctx-1",
            "messages": [],
        },
    },
    "withSystemMessage": {
        "summary": "Context with a system message",
        "value": {
            "context_id": "ctx-1",
            "messages": [
                _text_message("You are concise and practical.", role="system")
            ],
            "metadata": {"topic": "support"},
        },
    },
})


CONTENT_MESSAGE_EXAMPLES = _openapi_examples({
    "userText": {
        "summary": "Append one user message",
        "value": _text_message("Remember that I prefer short answers."),
    },
    "systemText": {
        "summary": "Append one system message",
        "value": _text_message("Always answer in JSON.", role="system"),
    },
})


SESSION_EXAMPLES = _openapi_examples({
    "minimal": {
        "summary": "Conversation session",
        "description": "The session references a context, provider, and model.",
        "value": {
            "session_id": "session-1",
            "title": "Planning chat",
            "context_id": "ctx-1",
            "provider_id": "main",
            "model_id": "gpt-4.1-mini",
        },
    },
})


SESSION_CHAT_EXAMPLES = _openapi_examples({
    "minimal": {
        "summary": "Smallest session chat",
        "description": "Provider, model, and context come from the session.",
        "value": {
            "messages": [_text_message("Summarize our current plan.")],
        },
    },
    "streamEquivalent": {
        "summary": "Request shape used by session agent flows",
        "description": "Session chat is not a streaming endpoint; use agent run streams for trace SSE.",
        "value": {
            "messages": [_text_message("Give me the next action only.")],
            "metadata": {"request_id": "session-chat-1"},
        },
    },
    "withMemory": {
        "summary": "Session chat with memory selection",
        "value": {
            "messages": [_text_message("Apply my preferences.")],
            "memory_query": {
                "scope": "session",
                "scope_id": "session-1",
                "limit": 5,
            },
        },
    },
    "overrideProvider": {
        "summary": "Override provider and model for this request",
        "description": "Request values win over the session defaults.",
        "value": {
            "provider_id": "main",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Use this provider for this turn.")],
        },
    },
    "withReasoningEffort": {
        "summary": "Session chat with reasoning effort",
        "value": {
            "messages": [_text_message("Give a careful answer.")],
            "metadata": {"reasoning_effort": "high"},
        },
    },
})


SESSION_AGENT_RUN_EXAMPLES = _openapi_examples({
    "minimal": {
        "summary": "Smallest session agent run",
        "value": {
            "messages": [_text_message("Use available tools if needed.")],
            "max_tool_rounds": 1,
            "write_memory": False,
        },
    },
    "overrideProvider": {
        "summary": "Start a session agent run with a request provider",
        "description": "Request provider and model override the session defaults.",
        "value": {
            "provider_id": "main",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Use this provider for this agent run.")],
            "max_tool_rounds": 1,
        },
    },
    "traceOnly": {
        "summary": "Plain traced model step",
        "description": "No tool rounds; useful when you want run state and trace records.",
        "value": {
            "messages": [_text_message("Answer once and stop.")],
            "max_tool_rounds": 0,
            "write_memory": False,
        },
    },
    "withReasoningEffort": {
        "summary": "Session agent run with reasoning effort",
        "value": {
            "messages": [_text_message("Plan the next step carefully.")],
            "max_tool_rounds": 0,
            "metadata": {"reasoning_effort": "high"},
        },
    },
})


AGENT_RUN_EXAMPLES = _openapi_examples({
    "minimal": {
        "summary": "Smallest agent run",
        "description": "Create `main` and `ctx-1` first. This performs one model step.",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Answer and stop.")],
            "max_tool_rounds": 0,
        },
    },
    "streamReady": {
        "summary": "Same body for `/agent-runs/stream`",
        "description": "Use this exact body with the streaming endpoint to receive trace SSE.",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Stream trace events while answering.")],
            "max_tool_rounds": 0,
            "metadata": {"request_id": "agent-stream-1"},
        },
    },
    "withTools": {
        "summary": "Run an agent with tool approval pauses",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Inspect the workspace if needed.")],
            "tools": [_tool_definition()],
            "max_tool_rounds": 2,
            "pause_on_approval": True,
        },
    },
    "withReasoningEffort": {
        "summary": "Agent run with reasoning effort",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Reason carefully, then stop.")],
            "max_tool_rounds": 0,
            "metadata": {"reasoning_effort": "high"},
        },
    },
})


RESUME_AGENT_RUN_EXAMPLES = _openapi_examples({
    "approveTool": {
        "summary": "Resume with an approved tool call",
        "value": {
            "approvals": [
                {
                    "approval_id": "approval-1",
                    "tool_call_id": "tool-call-1",
                    "status": "approved",
                }
            ]
        },
    },
    "denyTool": {
        "summary": "Resume with a denied tool call",
        "value": {
            "approvals": [
                {
                    "approval_id": "approval-1",
                    "tool_call_id": "tool-call-1",
                    "status": "denied",
                    "reason": "Not allowed for this run.",
                }
            ]
        },
    },
})


RENDER_SKILL_EXAMPLES = _openapi_examples({
    "minimal": {
        "summary": "Render a skill prompt",
        "value": {
            "variables": {"topic": "EvernightAI"},
        },
    },
})


MEMORY_ITEM_EXAMPLES = _openapi_examples({
    "preference": {
        "summary": "Store a user preference",
        "value": {
            "memory_id": "mem-1",
            "content": "Prefer concise answers.",
            "kind": "preference",
            "scope": "user",
            "scope_id": "user-1",
            "tags": ["style"],
            "priority": 10,
        },
    },
    "sessionFact": {
        "summary": "Store a session fact",
        "value": {
            "memory_id": "mem-session-1",
            "content": "The current project is EvernightAI.",
            "kind": "fact",
            "scope": "session",
            "scope_id": "session-1",
        },
    },
})


MEMORY_QUERY_EXAMPLES = _openapi_examples({
    "session": {
        "summary": "Select session memories",
        "value": {
            "scope": "session",
            "scope_id": "session-1",
            "limit": 5,
        },
    },
    "userPreferences": {
        "summary": "Select user preferences",
        "value": {
            "scope": "user",
            "scope_id": "user-1",
            "kinds": ["preference"],
            "tags": ["style"],
            "limit": 3,
        },
    },
})
