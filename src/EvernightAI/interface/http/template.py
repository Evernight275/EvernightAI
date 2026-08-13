from typing import Any, cast

from fastapi.openapi.models import Example

from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunState, AgentRunStatus
from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    ChatSkill,
    ChatUsage,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.data_analysis import (
    DataAnalysisRequest,
    DataSort,
    DataSortDirection,
    DataStatisticsRequest,
)
from EvernightAI.core.schema.memory import (
    MemoryItem,
    MemoryKind,
    MemoryQuery,
    MemoryScope,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
    SessionChatResult,
)
from EvernightAI.core.schema.tool import (
    ToolApprovalDecision,
    ToolApprovalStatus,
    ToolDefinition,
)
from EvernightAI.interface.http.schema import (
    AgentRunControlRequest,
    ChatWithContextRequest,
    DirectChatRequest,
    RenderSkillRequest,
    ResumeAgentRunRequest,
)


API_DESCRIPTION = """
EvernightAI HTTP API exposes an assembled runtime for providers, chat, context,
memory, data analysis, skills, tools, sessions, and agent runs.

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
    {"name": "health", "description": "Readiness check."},
    {
        "name": "providers",
        "description": "Register provider instances and inspect declared models.",
    },
    {"name": "chat", "description": "Direct chat calls and context-aware chat calls."},
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
        "name": "data-analysis",
        "description": "Registered data sources, metrics, statistics, and analysis.",
    },
    {
        "name": "skills",
        "description": "Reusable prompt capabilities that can be rendered into chat.",
    },
    {
        "name": "tools",
        "description": "Registered external actions available to chat or agent flows.",
    },
    {
        "name": "logs",
        "description": "Recent in-memory process logs for the current HTTP service.",
    },
]


def _schema_value(
    schema: EvernightAISchema,
    *,
    exclude: set[str] | dict[str, Any] | None = None,
    exclude_defaults: bool = True,
) -> dict[str, Any]:
    return schema.model_dump(
        mode="json",
        exclude_none=True,
        exclude_defaults=exclude_defaults,
        exclude=exclude,
    )


def _example(
    *,
    summary: str,
    value: EvernightAISchema,
    description: str | None = None,
) -> dict[str, object]:
    example: dict[str, object] = {
        "summary": summary,
        "value": _schema_value(value),
    }
    if description is not None:
        example["description"] = description
    return example


def _response_example(
    *,
    description: str,
    value: EvernightAISchema,
    exclude: set[str] | dict[str, Any] | None = None,
    exclude_defaults: bool = True,
) -> dict[str, object]:
    return {
        "description": description,
        "content": {
            "application/json": {
                "example": _schema_value(
                    value,
                    exclude=exclude,
                    exclude_defaults=exclude_defaults,
                ),
            }
        },
    }


def _openapi_examples(examples: dict[str, object]) -> dict[str, Example]:
    return cast(dict[str, Example], examples)


def _message(text: str, *, role: MessageRole = MessageRole.USER) -> Content:
    return Content(
        role=role,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def _chat_request(
    text: str,
    *,
    metadata: dict[str, object] | None = None,
    skills: list[ChatSkill] | None = None,
) -> ChatRequest:
    return ChatRequest(
        model_id="gpt-4.1-mini",
        messages=[_message(text)],
        skills=skills,
        metadata=metadata or {},
    )


def _direct_chat_request(
    text: str,
    *,
    metadata: dict[str, object] | None = None,
    skills: list[ChatSkill] | None = None,
) -> DirectChatRequest:
    return DirectChatRequest(
        provider_id="main",
        request=_chat_request(text, metadata=metadata, skills=skills),
    )


def _context_chat_request(
    text: str,
    *,
    metadata: dict[str, object] | None = None,
    memory_query: MemoryQuery | None = None,
) -> ChatWithContextRequest:
    return ChatWithContextRequest(
        provider_id="main",
        context_id="ctx-1",
        model_id="gpt-4.1-mini",
        messages=[_message(text)],
        memory_query=memory_query,
        metadata=metadata,
    )


def _tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name="write_file",
        description="Write text to a workspace file.",
        parameters_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        requires_approval=True,
    )


def _agent_run_request(
    text: str,
    *,
    metadata: dict[str, object] | None = None,
    max_tool_rounds: int = 0,
    tools: list[ToolDefinition] | None = None,
) -> AgentRunRequest:
    return AgentRunRequest(
        provider_id="main",
        context_id="ctx-1",
        model_id="gpt-4.1-mini",
        messages=[_message(text)],
        max_tool_rounds=max_tool_rounds,
        tools=tools,
        pause_on_approval=tools is not None,
        metadata=metadata or {},
    )


def _statistics_request() -> DataStatisticsRequest:
    return DataStatisticsRequest(
        source_id="orders",
        metrics=["order_count", "revenue"],
        dimensions=["status"],
        sorts=[DataSort(field_id="revenue", direction=DataSortDirection.DESC)],
        limit=10,
    )


CHAT_RESPONSE_EXAMPLE = _response_example(
    description="Successful chat response.",
    value=ChatResponse(
        response_id="resp-1",
        model_id="gpt-4.1-mini",
        message=_message("Hello.", role=MessageRole.ASSISTANT),
        finish_reason="stop",
        usage=ChatUsage(
            prompt_tokens=12,
            completion_tokens=20,
            total_tokens=32,
        ),
    ),
)


SESSION_CHAT_RESPONSE_EXAMPLE = _response_example(
    description="Successful session chat response.",
    value=SessionChatResult(
        session=Session(
            session_id="session-1",
            title="Planning chat",
            context_id="ctx-1",
            provider_id="main",
            model_id="gpt-4.1-mini",
        ),
        response=ChatResponse(
            response_id="resp-1",
            model_id="gpt-4.1-mini",
            message=_message("Hello.", role=MessageRole.ASSISTANT),
            finish_reason="stop",
        ),
    ),
    exclude={"session": {"created_at", "updated_at"}},
)


AGENT_RUN_STATE_RESPONSE_EXAMPLE = _response_example(
    description="Agent run state.",
    value=AgentRunState(
        run_id="run-1",
        request=_agent_run_request(
            "Answer and stop.",
            metadata={"run_id": "run-1"},
        ),
        status=AgentRunStatus.FINISHED,
        metadata={"run_id": "run-1"},
    ),
)


AGENT_RUN_PAUSED_RESPONSE_EXAMPLE = _response_example(
    description="Paused agent run state.",
    value=AgentRunState(
        run_id="run-1",
        request=_agent_run_request(
            "Pause at the next safe checkpoint.",
            metadata={"run_id": "run-1"},
        ),
        status=AgentRunStatus.RUNNING,
        metadata={
            "run_id": "run-1",
            "agent_runtime": {
                "pause_requested": True,
                "pause_reason": "operator paused",
            },
        },
    ),
    exclude_defaults=False,
)


AGENT_RUN_CANCELED_RESPONSE_EXAMPLE = _response_example(
    description="Canceled agent run state.",
    value=AgentRunState(
        run_id="run-1",
        request=_agent_run_request(
            "Cancel this run.",
            metadata={"run_id": "run-1"},
        ),
        status=AgentRunStatus.CANCELED,
        metadata={
            "run_id": "run-1",
            "agent_runtime": {
                "manual_pause": False,
                "cancel_reason": "operator canceled",
            },
        },
    ),
)


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
    "openaiCompatible": _example(
        summary="OpenAI-compatible provider",
        description="Register a provider id that later chat requests can use.",
        value=ProviderConfig(
            provider_id="main",
            name="Main provider",
            type=ProviderType.OPENAI,
            api_key="sk-...",
            base_url="https://api.openai.com/v1",
            model={
                "gpt-4.1-mini": ProviderModelConfig(
                    model_id="gpt-4.1-mini",
                    capabilities=[ProviderModelCapability.CHAT],
                )
            },
        ),
    ),
    "anthropic": _example(
        summary="Anthropic provider",
        value=ProviderConfig(
            provider_id="anthropic-main",
            name="Anthropic",
            type=ProviderType.ANTHROPIC,
            api_key="sk-ant-...",
            model={
                "claude-3-5-haiku-latest": ProviderModelConfig(
                    model_id="claude-3-5-haiku-latest",
                    capabilities=[ProviderModelCapability.CHAT],
                )
            },
        ),
    ),
})


DIRECT_CHAT_EXAMPLES = _openapi_examples({
    "minimal": _example(
        summary="Smallest one-off chat",
        description="Use this after registering provider id `main`.",
        value=_direct_chat_request("Hello, give me a short answer."),
    ),
    "withMetadata": _example(
        summary="One-off chat with request metadata",
        description="Metadata is passed through for tracing; providers may ignore it.",
        value=_direct_chat_request(
            "Answer in one sentence.",
            metadata={"request_id": "req-1"},
        ),
    ),
    "withReasoningEffort": _example(
        summary="One-off chat with reasoning effort",
        description="OpenAI-compatible providers receive `reasoning_effort` as a provider request parameter.",
        value=_direct_chat_request(
            "Think carefully, then answer briefly.",
            metadata={"reasoning_effort": "high"},
        ),
    ),
    "withSkill": _example(
        summary="Chat with a skill prompt",
        value=_direct_chat_request(
            "Echo this request.",
            skills=[ChatSkill(skill_name="echo")],
        ),
    ),
})


CHAT_WITH_CONTEXT_EXAMPLES = _openapi_examples({
    "minimal": _example(
        summary="Smallest context chat",
        description="Create `ctx-1` first with `POST /contexts`.",
        value=_context_chat_request("Continue from the stored context."),
    ),
    "streamReady": _example(
        summary="Same body for `/chat/context/stream`",
        description="Use this exact body with the streaming endpoint.",
        value=_context_chat_request(
            "Stream the answer and save it.",
            metadata={"request_id": "stream-1"},
        ),
    ),
    "withSessionMemory": _example(
        summary="Chat with selected session memory",
        value=_context_chat_request(
            "Use my saved preference.",
            memory_query=MemoryQuery(
                scope=MemoryScope.SESSION,
                scope_id="session-1",
                limit=3,
            ),
            metadata={"request_id": "req-1"},
        ),
    ),
    "withReasoningEffort": _example(
        summary="Context chat with reasoning effort",
        value=_context_chat_request(
            "Reason through this before answering.",
            metadata={"reasoning_effort": "high"},
        ),
    ),
})


CONTEXT_EXAMPLES = _openapi_examples({
    "empty": _example(
        summary="Empty context",
        description="Create this first, then call `/chat/context`.",
        value=Context(context_id="ctx-1"),
    ),
    "withSystemMessage": _example(
        summary="Context with a system message",
        value=Context(
            context_id="ctx-1",
            messages=[
                _message(
                    "You are concise and practical.",
                    role=MessageRole.SYSTEM,
                )
            ],
            metadata={"topic": "support"},
        ),
    ),
})


CONTENT_MESSAGE_EXAMPLES = _openapi_examples({
    "userText": _example(
        summary="Append one user message",
        value=_message("Remember that I prefer short answers."),
    ),
    "systemText": _example(
        summary="Append one system message",
        value=_message("Always answer in JSON.", role=MessageRole.SYSTEM),
    ),
})


SESSION_EXAMPLES = _openapi_examples({
    "minimal": _example(
        summary="Conversation session",
        description="The session references a context, provider, and model.",
        value=Session(
            session_id="session-1",
            title="Planning chat",
            context_id="ctx-1",
            provider_id="main",
            model_id="gpt-4.1-mini",
        ),
    ),
})


SESSION_CHAT_EXAMPLES = _openapi_examples({
    "minimal": _example(
        summary="Smallest session chat",
        description="Provider, model, and context come from the session.",
        value=SessionChatRequest(
            messages=[_message("Summarize our current plan.")],
        ),
    ),
    "streamEquivalent": _example(
        summary="Request shape used by session agent flows",
        description="Session chat is not a streaming endpoint; use agent run streams for trace SSE.",
        value=SessionChatRequest(
            messages=[_message("Give me the next action only.")],
            metadata={"request_id": "session-chat-1"},
        ),
    ),
    "withMemory": _example(
        summary="Session chat with memory selection",
        value=SessionChatRequest(
            messages=[_message("Apply my preferences.")],
            memory_query=MemoryQuery(
                scope=MemoryScope.SESSION,
                scope_id="session-1",
                limit=5,
            ),
        ),
    ),
    "overrideProvider": _example(
        summary="Override provider and model for this request",
        description="Request values win over the session defaults.",
        value=SessionChatRequest(
            provider_id="main",
            model_id="gpt-4.1-mini",
            messages=[_message("Use this provider for this turn.")],
        ),
    ),
    "withReasoningEffort": _example(
        summary="Session chat with reasoning effort",
        value=SessionChatRequest(
            messages=[_message("Give a careful answer.")],
            metadata={"reasoning_effort": "high"},
        ),
    ),
})


SESSION_AGENT_RUN_EXAMPLES = _openapi_examples({
    "minimal": _example(
        summary="Smallest session agent run",
        value=SessionAgentRunRequest(
            messages=[_message("Use available tools if needed.")],
            max_tool_rounds=1,
            write_memory=False,
        ),
    ),
    "overrideProvider": _example(
        summary="Start a session agent run with a request provider",
        description="Request provider and model override the session defaults.",
        value=SessionAgentRunRequest(
            provider_id="main",
            model_id="gpt-4.1-mini",
            messages=[_message("Use this provider for this agent run.")],
            max_tool_rounds=1,
        ),
    ),
    "traceOnly": _example(
        summary="Plain traced model step",
        description="No tool rounds; useful when you want run state and trace records.",
        value=SessionAgentRunRequest(
            messages=[_message("Answer once and stop.")],
            max_tool_rounds=0,
            write_memory=False,
        ),
    ),
    "withReasoningEffort": _example(
        summary="Session agent run with reasoning effort",
        value=SessionAgentRunRequest(
            messages=[_message("Plan the next step carefully.")],
            max_tool_rounds=0,
            metadata={"reasoning_effort": "high"},
        ),
    ),
})


AGENT_RUN_EXAMPLES = _openapi_examples({
    "minimal": _example(
        summary="Smallest agent run",
        description="Create `main` and `ctx-1` first. This performs one model step.",
        value=_agent_run_request("Answer and stop."),
    ),
    "streamReady": _example(
        summary="Same body for `/agent-runs/stream`",
        description="Use this exact body with the streaming endpoint to receive trace SSE.",
        value=_agent_run_request(
            "Stream trace events while answering.",
            metadata={"request_id": "agent-stream-1"},
        ),
    ),
    "withTools": _example(
        summary="Run an agent with tool approval pauses",
        value=_agent_run_request(
            "Inspect the workspace if needed.",
            max_tool_rounds=2,
            tools=[_tool_definition()],
        ),
    ),
    "withReasoningEffort": _example(
        summary="Agent run with reasoning effort",
        value=_agent_run_request(
            "Reason carefully, then stop.",
            metadata={"reasoning_effort": "high"},
        ),
    ),
})


RESUME_AGENT_RUN_EXAMPLES = _openapi_examples({
    "approveTool": _example(
        summary="Resume with an approved tool call",
        value=ResumeAgentRunRequest(
            approvals=[
                ToolApprovalDecision(
                    approval_id="approval-1",
                    tool_call_id="tool-call-1",
                    status=ToolApprovalStatus.APPROVED,
                )
            ]
        ),
    ),
    "denyTool": _example(
        summary="Resume with a denied tool call",
        value=ResumeAgentRunRequest(
            approvals=[
                ToolApprovalDecision(
                    approval_id="approval-1",
                    tool_call_id="tool-call-1",
                    status=ToolApprovalStatus.DENIED,
                    reason="Not allowed for this run.",
                )
            ]
        ),
    ),
})


AGENT_RUN_CONTROL_EXAMPLES = _openapi_examples({
    "withReason": _example(
        summary="Control with a reason",
        value=AgentRunControlRequest(reason="operator paused"),
    ),
    "withoutReason": _example(
        summary="Control without a reason",
        value=AgentRunControlRequest(),
    ),
})


RENDER_SKILL_EXAMPLES = _openapi_examples({
    "minimal": _example(
        summary="Render a skill prompt",
        value=RenderSkillRequest(variables={"topic": "EvernightAI"}),
    ),
})


MEMORY_ITEM_EXAMPLES = _openapi_examples({
    "preference": _example(
        summary="Store a user preference",
        value=MemoryItem(
            memory_id="mem-1",
            content="Prefer concise answers.",
            kind=MemoryKind.PREFERENCE,
            scope=MemoryScope.USER,
            scope_id="user-1",
            tags=["style"],
            priority=10,
        ),
    ),
    "sessionFact": _example(
        summary="Store a session fact",
        value=MemoryItem(
            memory_id="mem-session-1",
            content="The current project is EvernightAI.",
            kind=MemoryKind.FACT,
            scope=MemoryScope.SESSION,
            scope_id="session-1",
        ),
    ),
})


MEMORY_QUERY_EXAMPLES = _openapi_examples({
    "session": _example(
        summary="Select session memories",
        value=MemoryQuery(
            scope=MemoryScope.SESSION,
            scope_id="session-1",
            limit=5,
        ),
    ),
    "userPreferences": _example(
        summary="Select user preferences",
        value=MemoryQuery(
            scope=MemoryScope.USER,
            scope_id="user-1",
            kinds=[MemoryKind.PREFERENCE],
            tags=["style"],
            limit=3,
        ),
    ),
})


DATA_STATISTICS_EXAMPLES = _openapi_examples({
    "ordersByStatus": _example(
        summary="Aggregate order metrics by status",
        value=_statistics_request(),
    ),
})


DATA_ANALYSIS_EXAMPLES = _openapi_examples({
    "fromStatistics": _example(
        summary="Analyze a statistics request",
        value=DataAnalysisRequest(
            source_id="orders",
            question="Which order status generated the most revenue?",
            statistics_request=_statistics_request(),
        ),
    ),
})
