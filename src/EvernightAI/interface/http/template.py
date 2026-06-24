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

Most request bodies below show the smallest useful JSON first. Optional fields
such as `skills`, `tools`, `memory_query`, and `metadata` are advanced controls.
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


def _openapi_examples(examples: dict[str, object]) -> dict[str, Example]:
    return cast(dict[str, Example], examples)


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
        "summary": "One-off chat",
        "description": "Use this after registering provider id `main`.",
        "value": {
            "provider_id": "main",
            "request": {
                "model_id": "gpt-4.1-mini",
                "messages": [_text_message("Hello, give me a short answer.")],
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
        "summary": "Chat and save context history",
        "description": "Context messages are sent before these request messages.",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Continue from the stored context.")],
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
        "summary": "Send a message to a session",
        "description": "Provider, model, and context come from the session.",
        "value": {
            "messages": [_text_message("Summarize our current plan.")],
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
})


SESSION_AGENT_RUN_EXAMPLES = _openapi_examples({
    "minimal": {
        "summary": "Start an agent run for a session",
        "value": {
            "messages": [_text_message("Use available tools if needed.")],
            "max_tool_rounds": 1,
            "write_memory": False,
        },
    },
})


AGENT_RUN_EXAMPLES = _openapi_examples({
    "minimal": {
        "summary": "Run an agent once",
        "description": "Set `max_tool_rounds` to 0 for a plain model step.",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Answer and stop.")],
            "max_tool_rounds": 0,
        },
    },
    "withTools": {
        "summary": "Run an agent with tool approval pauses",
        "value": {
            "provider_id": "main",
            "context_id": "ctx-1",
            "model_id": "gpt-4.1-mini",
            "messages": [_text_message("Inspect the workspace if needed.")],
            "max_tool_rounds": 2,
            "pause_on_approval": True,
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
