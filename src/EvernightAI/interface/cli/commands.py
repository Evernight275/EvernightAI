import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError as PydanticValidationError

from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunState
from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
)
from EvernightAI.core.schema.skill import SkillCapability, SkillRenderRequest
from EvernightAI.core.schema.tool import ToolApprovalDecision, ToolApprovalStatus
from EvernightAI.interface.cli.config import load_config
from EvernightAI.interface.cli.schema import EvernightConfig


SchemaT = TypeVar("SchemaT", bound=EvernightAISchema)


def check_config(path: str | Path) -> str:
    config = load_config(path)
    return format_config_summary(config)


def show_config(path: str | Path) -> str:
    config = load_config(path)
    return json.dumps(
        redact_config(config),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def list_providers(config: EvernightConfig) -> str:
    if not config.providers:
        return "No providers declared."

    rows = [
        [
            provider.provider_id,
            provider.name,
            provider.type.value,
            "yes" if provider.is_enabled else "no",
            str(len(provider.model)),
        ]
        for provider in config.providers
    ]
    return _format_table(
        ["PROVIDER ID", "NAME", "TYPE", "ENABLED", "MODELS"],
        rows,
    )


def list_models(config: EvernightConfig, provider_id: str) -> str:
    provider = _find_provider(config, provider_id)
    if provider is None:
        raise ConfigurationError(
            f"Provider '{provider_id}' is not declared in config"
        )

    if not provider.model:
        return f"No models declared for provider '{provider_id}'."

    rows = [
        [
            model.model_id,
            ", ".join(
                capability.value for capability in model.capabilities
            )
            or "-",
        ]
        for model in provider.model.values()
    ]
    return _format_table(["MODEL ID", "CAPABILITIES"], rows)


async def list_contexts(interface: EvernightInterfaceProtocol) -> str:
    contexts = await interface.chat.list_contexts()
    if not contexts:
        return "No contexts stored."

    rows = [
        [
            context.context_id,
            str(len(context.messages)),
        ]
        for context in contexts
    ]
    return _format_table(["CONTEXT ID", "MESSAGES"], rows)


async def get_context(interface: EvernightInterfaceProtocol, context_id: str) -> str:
    return _dump_model(await interface.chat.get_context(context_id))


async def create_context(
    interface: EvernightInterfaceProtocol,
    payload_json: str,
) -> str:
    context = _schema_from_json(payload_json, Context)
    return _dump_model(await interface.chat.create_context(context))


async def replace_context(
    interface: EvernightInterfaceProtocol,
    context_id: str,
    payload_json: str,
) -> str:
    context = _schema_from_json(payload_json, Context)
    if context.context_id != context_id:
        context = context.model_copy(update={"context_id": context_id})

    return _dump_model(await interface.chat.replace_context(context))


async def append_context_message(
    interface: EvernightInterfaceProtocol,
    context_id: str,
    message_json: str,
) -> str:
    message = _schema_from_json(message_json, Content)
    return _dump_model(await interface.chat.append_context(context_id, message))


async def delete_context(interface: EvernightInterfaceProtocol, context_id: str) -> str:
    await interface.chat.delete_context(context_id)
    return ""


async def list_memories(interface: EvernightInterfaceProtocol) -> str:
    memories = await interface.chat.list_memories()
    if not memories:
        return "No memories stored."

    rows = [
        [
            memory.memory_id,
            memory.kind.value,
            memory.scope.value,
            memory.scope_id or "-",
            "yes" if memory.is_enabled else "no",
            memory.content,
        ]
        for memory in memories
    ]
    return _format_table(
        ["MEMORY ID", "KIND", "SCOPE", "SCOPE ID", "ENABLED", "CONTENT"],
        rows,
    )


async def get_memory(interface: EvernightInterfaceProtocol, memory_id: str) -> str:
    return _dump_model(await interface.chat.get_memory(memory_id))


async def create_memory(
    interface: EvernightInterfaceProtocol,
    payload_json: str,
) -> str:
    memory = _schema_from_json(payload_json, MemoryItem)
    return _dump_model(await interface.chat.create_memory(memory))


async def select_memories(
    interface: EvernightInterfaceProtocol,
    query_json: str | None,
) -> str:
    query = None if query_json is None else _schema_from_json(query_json, MemoryQuery)
    return _dump_model(await interface.chat.select_memories(query))


async def delete_memory(interface: EvernightInterfaceProtocol, memory_id: str) -> str:
    await interface.chat.delete_memory(memory_id)
    return ""


async def list_sessions(interface: EvernightInterfaceProtocol) -> str:
    sessions = await interface.sessions.list_sessions()
    if not sessions:
        return "No sessions stored."

    rows = [
        [
            session.session_id,
            session.status.value,
            session.context_id,
            session.provider_id or "-",
            session.model_id or "-",
            session.title or "-",
        ]
        for session in sessions
    ]
    return _format_table(
        ["SESSION ID", "STATUS", "CONTEXT", "PROVIDER", "MODEL", "TITLE"],
        rows,
    )


async def get_session(interface: EvernightInterfaceProtocol, session_id: str) -> str:
    return _dump_model(await interface.sessions.get_session(session_id))


async def create_session(
    interface: EvernightInterfaceProtocol,
    payload_json: str,
) -> str:
    session = _schema_from_json(payload_json, Session)
    return _dump_model(await interface.sessions.create_session(session))


async def replace_session(
    interface: EvernightInterfaceProtocol,
    session_id: str,
    payload_json: str,
) -> str:
    session = _schema_from_json(payload_json, Session)
    if session.session_id != session_id:
        session = session.model_copy(update={"session_id": session_id})

    return _dump_model(await interface.sessions.replace_session(session))


async def archive_session(
    interface: EvernightInterfaceProtocol,
    session_id: str,
) -> str:
    return _dump_model(await interface.sessions.archive_session(session_id))


async def delete_session(interface: EvernightInterfaceProtocol, session_id: str) -> str:
    await interface.sessions.delete_session(session_id)
    return ""


async def chat_with_session(
    interface: EvernightInterfaceProtocol,
    session_id: str,
    request_json: str,
) -> str:
    request = _schema_from_json(request_json, SessionChatRequest)
    return _dump_model(await interface.sessions.chat_with_session(session_id, request))


async def start_session_agent_run(
    interface: EvernightInterfaceProtocol,
    session_id: str,
    request_json: str,
) -> str:
    request = _schema_from_json(request_json, SessionAgentRunRequest)
    return _dump_model(
        await interface.sessions.start_agent_run_for_session(session_id, request)
    )


def list_agent_runs(interface: EvernightInterfaceProtocol) -> str:
    states = interface.agent_runs.list_states()
    if not states:
        return "No agent runs stored."

    rows = [
        [
            state.run_id,
            state.status.value,
            state.request.context_id,
            state.request.model_id,
            str(len(state.pending_approval_requests)),
        ]
        for state in states
    ]
    return _format_table(
        ["RUN ID", "STATUS", "CONTEXT", "MODEL", "PENDING APPROVALS"],
        rows,
    )


def get_agent_run(interface: EvernightInterfaceProtocol, run_id: str) -> str:
    return _dump_model(interface.agent_runs.get_state(run_id))


def list_agent_trace(interface: EvernightInterfaceProtocol, run_id: str) -> str:
    return _dump_models(interface.agent_runs.list_trace(run_id))


async def start_agent_run(
    interface: EvernightInterfaceProtocol,
    request_json: str,
) -> str:
    request = _schema_from_json(request_json, AgentRunRequest)
    return _dump_model(await interface.agent_runs.start(request))


async def resume_agent_run(
    interface: EvernightInterfaceProtocol,
    run_id: str,
    approvals_json: str,
) -> str:
    approvals = _schema_list_from_json(approvals_json, ToolApprovalDecision)
    return _dump_model(await interface.agent_runs.resume(run_id, approvals))


async def approve_pending_agent_run(
    interface: EvernightInterfaceProtocol,
    run_id: str,
) -> str:
    state = interface.agent_runs.get_state(run_id)
    approvals = _approve_pending_tool_calls(state)
    return _dump_model(await interface.agent_runs.resume(run_id, approvals))


def _approve_pending_tool_calls(state: AgentRunState) -> list[ToolApprovalDecision]:
    return [
        ToolApprovalDecision(
            approval_id=request.approval_id,
            tool_call_id=request.tool_call_id,
            status=ToolApprovalStatus.APPROVED,
        )
        for request in state.pending_approval_requests
    ]


def list_skills(interface: EvernightInterfaceProtocol) -> str:
    skills = interface.skills.list_skills()
    if not skills:
        return "No skills registered."

    rows = [
        [
            skill.name,
            ", ".join(capability.value for capability in skill.capabilities) or "-",
            ", ".join(skill.required_tools) or "-",
            skill.description,
        ]
        for skill in skills
    ]
    return _format_table(
        ["SKILL", "CAPABILITIES", "TOOLS", "DESCRIPTION"],
        rows,
    )


def show_skill(interface: EvernightInterfaceProtocol, skill_name: str) -> str:
    skill = interface.skills.get_skill(skill_name)
    return json.dumps(
        skill.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def skill_supports(
    interface: EvernightInterfaceProtocol,
    skill_name: str,
    capability: SkillCapability,
) -> str:
    supported = interface.skills.skill_supports(skill_name, capability)
    return "yes" if supported else "no"


async def render_skill(
    interface: EvernightInterfaceProtocol,
    *,
    skill_name: str,
    render_id: str,
    variables: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
) -> str:
    rendered = await interface.skills.render_skill(
        SkillRenderRequest(
            render_id=render_id,
            skill_name=skill_name,
            variables=variables or {},
            metadata=metadata or {},
        )
    )
    return json.dumps(
        rendered.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


async def run_chat(
    interface: EvernightInterfaceProtocol,
    config: EvernightConfig,
    *,
    provider_id: str,
    model_id: str,
    prompt: str,
) -> str:
    provider_config = _find_provider(config, provider_id)
    if provider_config is None:
        raise ConfigurationError(
            f"Provider '{provider_id}' is not declared in config"
        )
    if not provider_config.is_enabled:
        raise ConfigurationError(
            f"Provider '{provider_id}' is disabled in config"
        )

    await interface.providers.create_provider(provider_config)
    request = ChatRequest(
        model_id=model_id,
        messages=[
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text=prompt)],
            )
        ],
    )
    response = await interface.chat.chat(provider_id, request)
    return _extract_text(response.message)


def format_config_summary(config: EvernightConfig) -> str:
    enabled_providers = [
        provider
        for provider in config.providers
        if provider.is_enabled
    ]
    mcp_servers = list(config.tools.mcp.server.values())
    lines = [
        "Config OK",
        f"runtime.database_path: {config.runtime.database_path}",
        f"http: {config.http.host}:{config.http.port}",
        f"providers: {len(config.providers)}",
        f"providers.enabled: {len(enabled_providers)}",
        f"tools.filesystem.enabled: {config.tools.filesystem.enabled}",
        f"tools.shell.enabled: {config.tools.shell.enabled}",
        f"tools.shell.allowed_commands: {len(config.tools.shell.allowed_commands)}",
        f"tools.shell.blocked_commands: {len(config.tools.shell.blocked_commands)}",
        f"tools.mcp.servers: {len(mcp_servers)}",
        f"tools.mcp.servers.enabled: {sum(server.enabled for server in mcp_servers)}",
    ]

    return "\n".join(lines)


def redact_config(config: EvernightConfig) -> dict[str, Any]:
    payload = config.model_dump(mode="json")
    providers = payload.get("providers")
    if isinstance(providers, list):
        for provider in providers:
            if isinstance(provider, dict) and provider.get("api_key"):
                provider["api_key"] = "***"

    return payload


def _find_provider(
    config: EvernightConfig,
    provider_id: str,
) -> ProviderConfig | None:
    for provider in config.providers:
        if provider.provider_id == provider_id:
            return provider

    return None


def _extract_text(message: Content) -> str:
    if not message.content:
        return ""

    return "".join(
        part.text or ""
        for part in message.content
        if part.type is ContentPartType.TEXT
    )


def _dump_model(model: EvernightAISchema) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def _dump_models(models: Sequence[EvernightAISchema]) -> str:
    return json.dumps(
        [model.model_dump(mode="json") for model in models],
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def _schema_from_json(value: str, schema: type[SchemaT]) -> SchemaT:
    parsed = _json_object(value)
    try:
        return schema.model_validate(parsed)
    except PydanticValidationError as exc:
        raise ConfigurationError("Invalid JSON payload", detail=str(exc)) from exc


def _schema_list_from_json(value: str, schema: type[SchemaT]) -> list[SchemaT]:
    parsed = _json_value(value)
    if not isinstance(parsed, list):
        raise ConfigurationError("Expected a JSON array")

    try:
        return [schema.model_validate(item) for item in parsed]
    except PydanticValidationError as exc:
        raise ConfigurationError("Invalid JSON payload", detail=str(exc)) from exc


def _json_object(value: str) -> dict[str, object]:
    parsed = _json_value(value)
    if not isinstance(parsed, dict):
        raise ConfigurationError("Expected a JSON object")

    return {
        key: item
        for key, item in parsed.items()
        if isinstance(key, str)
    }


def _json_value(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("Invalid JSON payload", detail=str(exc)) from exc


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = {
        header: max(
            len(header),
            *(len(row[index]) for row in rows),
        )
        for index, header in enumerate(headers)
    }
    header_line = "  ".join(header.ljust(widths[header]) for header in headers)
    body_lines = [
        "  ".join(
            row[index].ljust(widths[header])
            for index, header in enumerate(headers)
        )
        for row in rows
    ]
    return "\n".join([header_line, *body_lines])
