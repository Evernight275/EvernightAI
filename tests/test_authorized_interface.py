from typing import cast

import pytest

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import (
    AuthorizedEvernightInterface,
    AuthorizedAgentInterface,
    AuthorizedAgentRunInterface,
    AuthorizedChatInterface,
    AuthorizedDataAnalysisInterface,
    AuthorizedProviderInterface,
    AuthorizedSessionInterface,
    AuthorizedSkillInterface,
    AuthorizedToolInterface,
    require_permission,
)
from EvernightAI.core.error.auth import AuthPermissionDeniedError
from EvernightAI.core.protocol.auth import AuthorizerProtocol
from EvernightAI.core.protocol.interface import (
    AgentInterfaceProtocol,
    AgentRunInterfaceProtocol,
    ChatInterfaceProtocol,
    DataAnalysisInterfaceProtocol,
    ProviderInterfaceProtocol,
    SessionInterfaceProtocol,
    SkillInterfaceProtocol,
    ToolInterfaceProtocol,
)
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunState
from EvernightAI.core.schema.auth import AuthRequest, Principal
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.data_analysis import (
    DataAnalysisRequest,
    DataAnalysisResult,
    DataFieldDefinition,
    DataMetricDefinition,
    DataSourceDefinition,
    DataStatisticsRequest,
    DataStatisticsResult,
)
from EvernightAI.core.schema.memory import MemoryItem, MemoryQuery
from EvernightAI.core.schema.provider import ProviderConfig, ProviderType
from EvernightAI.core.schema.provider import (
    ProviderModelCapability,
)
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
)
from EvernightAI.core.schema.skill import (
    SkillCapability,
    SkillRenderRequest,
)
from EvernightAI.core.schema.tool import ToolApprovalDecision


def test_require_permission_uses_resource_action_permission_key() -> None:
    principal = Principal(principal_id="user-1", permissions=["tools:list"])

    require_permission(
        Authorizer(PermissionAuthPolicy()),
        principal,
        "tools",
        "list",
    )


def test_require_permission_rejects_missing_permission() -> None:
    principal = Principal(principal_id="user-1")

    with pytest.raises(AuthPermissionDeniedError) as exc_info:
        require_permission(
            Authorizer(PermissionAuthPolicy()),
            principal,
            "providers",
            "create",
            "provider-1",
        )

    assert "providers:create" in str(exc_info.value)


@pytest.mark.asyncio
async def test_authorized_interface_delegates_when_permission_is_allowed() -> None:
    interface = _authorized_interface(
        permissions=[
            "providers:create",
            "contexts:create",
            "tools:list",
            "data-analysis:list",
        ]
    )

    provider = await interface.providers.create_provider(
        ProviderConfig(
            provider_id="provider-1",
            name="Fake",
            type=ProviderType.OPENAI,
        )
    )
    context = await interface.chat.create_context(
        Context(context_id="ctx-1", messages=[])
    )
    tools = interface.tools.list_tools()
    data_sources = interface.data_analysis.list_data_sources()

    assert provider.provider_id == "provider-1"
    assert context.context_id == "ctx-1"
    assert tools == []
    assert data_sources == []


@pytest.mark.asyncio
async def test_authorized_interface_stops_denied_call_before_inner_work() -> None:
    runtime = create_runtime()
    interface = AuthorizedEvernightInterface(
        create_interface(runtime),
        Authorizer(PermissionAuthPolicy()),
        Principal(principal_id="user-1"),
    )

    with pytest.raises(AuthPermissionDeniedError):
        await interface.providers.create_provider(
            ProviderConfig(
                provider_id="provider-1",
                name="Fake",
                type=ProviderType.OPENAI,
            )
        )

    assert await runtime.providers.list_instances() == []


def test_authorized_interface_preserves_runtime_and_close_delegation() -> None:
    runtime = create_runtime()
    inner = create_interface(runtime)
    interface = AuthorizedEvernightInterface(
        inner,
        Authorizer(PermissionAuthPolicy()),
        Principal(principal_id="user-1", permissions=["*"]),
    )

    assert interface.runtime is runtime


def make_message(text: str) -> Content:
    return Content(
        role=MessageRole.USER,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def make_agent_request(context_id: str) -> AgentRunRequest:
    return AgentRunRequest(
        provider_id="provider-1",
        context_id=context_id,
        model_id="model-1",
        messages=[],
    )


def make_agent_state(run_id: str) -> AgentRunState:
    return AgentRunState(run_id=run_id, request=make_agent_request("ctx-1"))


def make_session(session_id: str) -> Session:
    return Session(session_id=session_id, context_id="ctx-1")


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs", "expected_resource", "expected_action", "expected_id"),
    [
        (
            "create_provider",
            (ProviderConfig(provider_id="provider-1", name="Fake", type=ProviderType.OPENAI),),
            {},
            "providers",
            "create",
            "provider-1",
        ),
        ("create_context", (Context(context_id="ctx-1"),), {}, "contexts", "create", "ctx-1"),
        ("get_context", ("ctx-1",), {}, "contexts", "get", "ctx-1"),
        (
            "append_context",
            ("ctx-1", make_message("hello")),
            {},
            "contexts",
            "append",
            "ctx-1",
        ),
        ("replace_context", (Context(context_id="ctx-1"),), {}, "contexts", "replace", "ctx-1"),
        ("list_contexts", (), {}, "contexts", "list", None),
        ("delete_context", ("ctx-1",), {}, "contexts", "delete", "ctx-1"),
        ("create_memory", (MemoryItem(memory_id="mem-1", content="memory"),), {}, "memories", "create", "mem-1"),
        ("get_memory", ("mem-1",), {}, "memories", "get", "mem-1"),
        ("list_memories", (), {}, "memories", "list", None),
        ("delete_memory", ("mem-1",), {}, "memories", "delete", "mem-1"),
        ("select_memories", (MemoryQuery(),), {}, "memories", "select", None),
        ("chat", ("provider-1", ChatRequest(model_id="model-1", messages=[])), {}, "chat", "create", "provider-1"),
        (
            "chat_with_context",
            ("provider-1", "ctx-1"),
            {"model_id": "model-1", "messages": []},
            "chat",
            "create",
            "ctx-1",
        ),
        (
            "chat_stream",
            ("provider-1", ChatRequest(model_id="model-1", messages=[])),
            {},
            "chat",
            "stream",
            "provider-1",
        ),
        (
            "chat_stream_with_context",
            ("provider-1", "ctx-1"),
            {"model_id": "model-1", "messages": []},
            "chat",
            "stream",
            "ctx-1",
        ),
    ],
)
@pytest.mark.asyncio
async def test_authorized_chat_interface_requires_expected_permission(
    method_name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    expected_resource: str,
    expected_action: str,
    expected_id: str | None,
) -> None:
    authorizer = RecordingAuthorizer()
    inner = FakeChatInterface()
    interface = AuthorizedChatInterface(
        cast(ChatInterfaceProtocol, inner),
        cast(AuthorizerProtocol, authorizer),
        Principal(principal_id="user-1"),
    )

    await getattr(interface, method_name)(*args, **kwargs)

    assert inner.calls == [method_name]
    assert authorizer.requests == [(expected_resource, expected_action, expected_id)]


@pytest.mark.parametrize(
    ("method_name", "args", "expected_resource", "expected_action", "expected_id"),
    [
        (
            "create_provider",
            (ProviderConfig(provider_id="provider-1", name="Fake", type=ProviderType.OPENAI),),
            "providers",
            "create",
            "provider-1",
        ),
        ("list_providers", (), "providers", "list", None),
        ("list_provider_models", ("provider-1",), "providers", "list_models", "provider-1"),
        ("get_provider_model", ("provider-1", "model-1"), "providers", "get_model", "provider-1"),
        (
            "provider_supports",
            ("provider-1", ProviderModelCapability.CHAT),
            "providers",
            "supports",
            "provider-1",
        ),
        ("delete_provider", ("provider-1",), "providers", "delete", "provider-1"),
    ],
)
@pytest.mark.asyncio
async def test_authorized_provider_interface_requires_expected_permission(
    method_name: str,
    args: tuple[object, ...],
    expected_resource: str,
    expected_action: str,
    expected_id: str | None,
) -> None:
    authorizer = RecordingAuthorizer()
    inner = FakeProviderInterface()
    interface = AuthorizedProviderInterface(
        cast(ProviderInterfaceProtocol, inner),
        cast(AuthorizerProtocol, authorizer),
        Principal(principal_id="user-1"),
    )

    await getattr(interface, method_name)(*args)

    assert inner.calls == [method_name]
    assert authorizer.requests == [(expected_resource, expected_action, expected_id)]


@pytest.mark.parametrize(
    ("method_name", "args", "expected_resource", "expected_action", "expected_id"),
    [
        ("run_agent", (make_agent_request("ctx-1"),), "agent", "run", "ctx-1"),
        ("run_agent_until_pause", (make_agent_request("ctx-1"),), "agent", "run", "ctx-1"),
        ("resume_agent", (make_agent_state("run-1"), []), "agent", "resume", "run-1"),
        (
            "resume_agent_until_pause",
            (make_agent_state("run-1"), []),
            "agent",
            "resume",
            "run-1",
        ),
        (
            "start_agent_run",
            (make_agent_request("ctx-1"),),
            "agent-runs",
            "create",
            "ctx-1",
        ),
        ("resume_agent_run", ("run-1", []), "agent-runs", "resume", "run-1"),
        ("run_agent_stream", (make_agent_request("ctx-1"),), "agent", "stream", "ctx-1"),
        (
            "resume_agent_stream",
            (make_agent_state("run-1"), []),
            "agent",
            "resume_stream",
            "run-1",
        ),
        (
            "run",
            ("provider-1", "ctx-1"),
            "agent",
            "run",
            "ctx-1",
        ),
    ],
)
@pytest.mark.asyncio
async def test_authorized_agent_interface_requires_expected_permission(
    method_name: str,
    args: tuple[object, ...],
    expected_resource: str,
    expected_action: str,
    expected_id: str | None,
) -> None:
    authorizer = RecordingAuthorizer()
    inner = FakeAgentInterface()
    interface = AuthorizedAgentInterface(
        cast(AgentInterfaceProtocol, inner),
        cast(AuthorizerProtocol, authorizer),
        Principal(principal_id="user-1"),
    )
    kwargs = {"model_id": "model-1", "messages": []} if method_name == "run" else {}

    result = getattr(interface, method_name)(*args, **kwargs)
    if hasattr(result, "__await__"):
        await result

    assert inner.calls == [method_name]
    assert authorizer.requests == [(expected_resource, expected_action, expected_id)]


@pytest.mark.parametrize(
    ("method_name", "args", "expected_resource", "expected_action", "expected_id"),
    [
        ("start", (make_agent_request("ctx-1"),), "agent-runs", "create", "ctx-1"),
        ("resume", ("run-1", []), "agent-runs", "resume", "run-1"),
        ("start_stream", (make_agent_request("ctx-1"),), "agent-runs", "stream", "ctx-1"),
        ("resume_stream", ("run-1", []), "agent-runs", "resume_stream", "run-1"),
        ("get_state", ("run-1",), "agent-runs", "get", "run-1"),
        ("list_states", (), "agent-runs", "list", None),
        ("list_trace", ("run-1",), "agent-runs", "list_trace", "run-1"),
    ],
)
@pytest.mark.asyncio
async def test_authorized_agent_run_interface_requires_expected_permission(
    method_name: str,
    args: tuple[object, ...],
    expected_resource: str,
    expected_action: str,
    expected_id: str | None,
) -> None:
    authorizer = RecordingAuthorizer()
    inner = FakeAgentRunInterface()
    interface = AuthorizedAgentRunInterface(
        cast(AgentRunInterfaceProtocol, inner),
        cast(AuthorizerProtocol, authorizer),
        Principal(principal_id="user-1"),
    )

    result = getattr(interface, method_name)(*args)
    if hasattr(result, "__await__"):
        await result

    assert inner.calls == [method_name]
    assert authorizer.requests == [(expected_resource, expected_action, expected_id)]


@pytest.mark.parametrize(
    ("method_name", "args", "expected_resource", "expected_action", "expected_id"),
    [
        ("list_skills", (), "skills", "list", None),
        ("get_skill", ("skill-1",), "skills", "get", "skill-1"),
        ("skill_supports", ("skill-1", SkillCapability.CHAT), "skills", "supports", "skill-1"),
        (
            "render_skill",
            (SkillRenderRequest(render_id="render-1", skill_name="skill-1"),),
            "skills",
            "render",
            "skill-1",
        ),
    ],
)
@pytest.mark.asyncio
async def test_authorized_skill_interface_requires_expected_permission(
    method_name: str,
    args: tuple[object, ...],
    expected_resource: str,
    expected_action: str,
    expected_id: str | None,
) -> None:
    authorizer = RecordingAuthorizer()
    inner = FakeSkillInterface()
    interface = AuthorizedSkillInterface(
        cast(SkillInterfaceProtocol, inner),
        cast(AuthorizerProtocol, authorizer),
        Principal(principal_id="user-1"),
    )

    result = getattr(interface, method_name)(*args)
    if hasattr(result, "__await__"):
        await result

    assert inner.calls == [method_name]
    assert authorizer.requests == [(expected_resource, expected_action, expected_id)]


@pytest.mark.parametrize(
    ("method_name", "args", "expected_resource", "expected_action", "expected_id"),
    [
        ("create_session", (make_session("session-1"),), "sessions", "create", "session-1"),
        ("get_session", ("session-1",), "sessions", "get", "session-1"),
        ("replace_session", (make_session("session-1"),), "sessions", "replace", "session-1"),
        ("archive_session", ("session-1",), "sessions", "archive", "session-1"),
        ("list_sessions", (), "sessions", "list", None),
        ("delete_session", ("session-1",), "sessions", "delete", "session-1"),
        (
            "chat_with_session",
            ("session-1", SessionChatRequest(provider_id="provider-1", model_id="model-1", messages=[])),
            "sessions",
            "chat",
            "session-1",
        ),
        (
            "start_agent_run_for_session",
            ("session-1", SessionAgentRunRequest(provider_id="provider-1", model_id="model-1", messages=[])),
            "sessions",
            "start_agent_run",
            "session-1",
        ),
    ],
)
@pytest.mark.asyncio
async def test_authorized_session_interface_requires_expected_permission(
    method_name: str,
    args: tuple[object, ...],
    expected_resource: str,
    expected_action: str,
    expected_id: str | None,
) -> None:
    authorizer = RecordingAuthorizer()
    inner = FakeSessionInterface()
    interface = AuthorizedSessionInterface(
        cast(SessionInterfaceProtocol, inner),
        cast(AuthorizerProtocol, authorizer),
        Principal(principal_id="user-1"),
    )

    await getattr(interface, method_name)(*args)

    assert inner.calls == [method_name]
    assert authorizer.requests == [(expected_resource, expected_action, expected_id)]


def test_authorized_tool_interface_requires_expected_permission() -> None:
    authorizer = RecordingAuthorizer()
    inner = FakeToolInterface()
    interface = AuthorizedToolInterface(
        cast(ToolInterfaceProtocol, inner),
        cast(AuthorizerProtocol, authorizer),
        Principal(principal_id="user-1"),
    )

    result = interface.list_tools()

    assert result == "delegated"
    assert inner.calls == ["list_tools"]
    assert authorizer.requests == [("tools", "list", None)]


@pytest.mark.parametrize(
    ("method_name", "args", "expected_action", "expected_id"),
    [
        ("list_data_sources", (), "list", None),
        ("get_data_source", ("orders",), "get", "orders"),
        ("list_data_fields", ("orders",), "list_fields", "orders"),
        ("list_data_metrics", ("orders",), "list_metrics", "orders"),
        (
            "run_statistics",
            (DataStatisticsRequest(source_id="orders", metrics=["order_count"]),),
            "statistics",
            "orders",
        ),
        (
            "analyze_data",
            (DataAnalysisRequest(source_id="orders"),),
            "analyze",
            "orders",
        ),
    ],
)
@pytest.mark.asyncio
async def test_authorized_data_analysis_interface_requires_expected_permission(
    method_name: str,
    args: tuple[object, ...],
    expected_action: str,
    expected_id: str | None,
) -> None:
    authorizer = RecordingAuthorizer()
    inner = FakeDataAnalysisInterface()
    interface = AuthorizedDataAnalysisInterface(
        cast(DataAnalysisInterfaceProtocol, inner),
        cast(AuthorizerProtocol, authorizer),
        Principal(principal_id="user-1"),
    )

    result = getattr(interface, method_name)(*args)
    if hasattr(result, "__await__"):
        await result

    assert inner.calls == [method_name]
    assert authorizer.requests == [("data-analysis", expected_action, expected_id)]


@pytest.mark.asyncio
async def test_authorized_chat_interface_stops_denied_call_before_inner_work() -> None:
    authorizer = RecordingAuthorizer(deny=True)
    inner = FakeChatInterface()
    interface = AuthorizedChatInterface(
        cast(ChatInterfaceProtocol, inner),
        cast(AuthorizerProtocol, authorizer),
        Principal(principal_id="user-1"),
    )

    with pytest.raises(AuthPermissionDeniedError):
        await interface.get_context("ctx-1")

    assert inner.calls == []
    assert authorizer.requests == [("contexts", "get", "ctx-1")]


def _authorized_interface(
    *,
    permissions: list[str],
) -> AuthorizedEvernightInterface:
    return AuthorizedEvernightInterface(
        create_interface(create_runtime()),
        Authorizer(PermissionAuthPolicy()),
        Principal(principal_id="user-1", permissions=permissions),
    )


class RecordingAuthorizer:
    def __init__(self, *, deny: bool = False) -> None:
        self.deny = deny
        self.requests: list[tuple[str, str, str | None]] = []

    def authorize(self, request: AuthRequest):
        raise NotImplementedError

    def require(self, request: AuthRequest) -> None:
        self.requests.append(
            (
                request.permission.resource,
                request.permission.action,
                request.resource_id,
            )
        )
        if self.deny:
            raise AuthPermissionDeniedError("denied")


class FakeChatInterface:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_provider(self, config: ProviderConfig) -> str:
        self.calls.append("create_provider")
        return "delegated"

    async def create_context(self, context: Context) -> str:
        self.calls.append("create_context")
        return "delegated"

    async def get_context(self, context_id: str) -> str:
        self.calls.append("get_context")
        return "delegated"

    async def append_context(self, context_id: str, message: Content) -> str:
        self.calls.append("append_context")
        return "delegated"

    async def replace_context(self, context: Context) -> str:
        self.calls.append("replace_context")
        return "delegated"

    async def list_contexts(self) -> str:
        self.calls.append("list_contexts")
        return "delegated"

    async def delete_context(self, context_id: str) -> str:
        self.calls.append("delete_context")
        return "delegated"

    async def create_memory(self, memory: MemoryItem) -> str:
        self.calls.append("create_memory")
        return "delegated"

    async def get_memory(self, memory_id: str) -> str:
        self.calls.append("get_memory")
        return "delegated"

    async def list_memories(self) -> str:
        self.calls.append("list_memories")
        return "delegated"

    async def delete_memory(self, memory_id: str) -> str:
        self.calls.append("delete_memory")
        return "delegated"

    async def select_memories(self, query: MemoryQuery | None = None) -> str:
        self.calls.append("select_memories")
        return "delegated"

    async def chat(self, provider_id: str, request: ChatRequest) -> str:
        self.calls.append("chat")
        return "delegated"

    async def chat_with_context(
        self,
        provider_id: str,
        context_id: str,
        **kwargs: object,
    ) -> str:
        self.calls.append("chat_with_context")
        return "delegated"

    async def chat_stream(self, provider_id: str, request: ChatRequest) -> str:
        self.calls.append("chat_stream")
        return "delegated"

    async def chat_stream_with_context(
        self,
        provider_id: str,
        context_id: str,
        **kwargs: object,
    ) -> str:
        self.calls.append("chat_stream_with_context")
        return "delegated"

    async def close(self) -> None:
        self.calls.append("close")


class FakeProviderInterface:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_provider(self, config: ProviderConfig) -> str:
        self.calls.append("create_provider")
        return "delegated"

    async def list_providers(self) -> str:
        self.calls.append("list_providers")
        return "delegated"

    async def list_provider_models(self, provider_id: str) -> str:
        self.calls.append("list_provider_models")
        return "delegated"

    async def get_provider_model(self, provider_id: str, model_id: str) -> str:
        self.calls.append("get_provider_model")
        return "delegated"

    async def provider_supports(
        self,
        provider_id: str,
        capability: ProviderModelCapability,
    ) -> str:
        self.calls.append("provider_supports")
        return "delegated"

    async def delete_provider(self, provider_id: str) -> str:
        self.calls.append("delete_provider")
        return "delegated"


class FakeToolInterface:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_tools(self) -> str:
        self.calls.append("list_tools")
        return "delegated"


class FakeDataAnalysisInterface:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_data_sources(self) -> list[DataSourceDefinition]:
        self.calls.append("list_data_sources")
        return []

    def get_data_source(self, source_id: str) -> DataSourceDefinition:
        self.calls.append("get_data_source")
        return DataSourceDefinition(source_id=source_id, name=source_id)

    def list_data_fields(self, source_id: str) -> list[DataFieldDefinition]:
        self.calls.append("list_data_fields")
        return []

    def list_data_metrics(self, source_id: str) -> list[DataMetricDefinition]:
        self.calls.append("list_data_metrics")
        return []

    async def run_statistics(
        self,
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        self.calls.append("run_statistics")
        return DataStatisticsResult(source_id=request.source_id)

    async def analyze_data(
        self,
        request: DataAnalysisRequest,
    ) -> DataAnalysisResult:
        self.calls.append("analyze_data")
        return DataAnalysisResult(source_id=request.source_id)


class FakeAgentInterface:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run_agent(self, request: AgentRunRequest) -> str:
        self.calls.append("run_agent")
        return "delegated"

    async def run_agent_until_pause(self, request: AgentRunRequest) -> str:
        self.calls.append("run_agent_until_pause")
        return "delegated"

    async def resume_agent(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> str:
        self.calls.append("resume_agent")
        return "delegated"

    async def resume_agent_until_pause(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> str:
        self.calls.append("resume_agent_until_pause")
        return "delegated"

    async def start_agent_run(self, request: AgentRunRequest) -> str:
        self.calls.append("start_agent_run")
        return "delegated"

    async def resume_agent_run(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> str:
        self.calls.append("resume_agent_run")
        return "delegated"

    def run_agent_stream(self, request: AgentRunRequest) -> str:
        self.calls.append("run_agent_stream")
        return "delegated"

    def resume_agent_stream(
        self,
        state: AgentRunState,
        approvals: list[ToolApprovalDecision],
    ) -> str:
        self.calls.append("resume_agent_stream")
        return "delegated"

    async def run(
        self,
        provider_id: str,
        context_id: str,
        **kwargs: object,
    ) -> str:
        self.calls.append("run")
        return "delegated"


class FakeAgentRunInterface:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start(self, request: AgentRunRequest) -> str:
        self.calls.append("start")
        return "delegated"

    async def resume(
        self,
        run_id: str,
        approvals: list[ToolApprovalDecision],
    ) -> str:
        self.calls.append("resume")
        return "delegated"

    def start_stream(self, request: AgentRunRequest) -> str:
        self.calls.append("start_stream")
        return "delegated"

    def resume_stream(self, run_id: str, approvals: list[ToolApprovalDecision]) -> str:
        self.calls.append("resume_stream")
        return "delegated"

    def get_state(self, run_id: str) -> str:
        self.calls.append("get_state")
        return "delegated"

    def list_states(self) -> str:
        self.calls.append("list_states")
        return "delegated"

    def list_trace(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> str:
        self.calls.append("list_trace")
        return "delegated"

    async def close(self) -> None:
        self.calls.append("close")


class FakeSkillInterface:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_skills(self) -> str:
        self.calls.append("list_skills")
        return "delegated"

    def get_skill(self, skill_name: str) -> str:
        self.calls.append("get_skill")
        return "delegated"

    def skill_supports(
        self,
        skill_name: str,
        capability: SkillCapability,
    ) -> str:
        self.calls.append("skill_supports")
        return "delegated"

    async def render_skill(self, request: SkillRenderRequest) -> str:
        self.calls.append("render_skill")
        return "delegated"


class FakeSessionInterface:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_session(self, session: Session) -> str:
        self.calls.append("create_session")
        return "delegated"

    async def get_session(self, session_id: str) -> str:
        self.calls.append("get_session")
        return "delegated"

    async def replace_session(self, session: Session) -> str:
        self.calls.append("replace_session")
        return "delegated"

    async def archive_session(self, session_id: str) -> str:
        self.calls.append("archive_session")
        return "delegated"

    async def list_sessions(self) -> str:
        self.calls.append("list_sessions")
        return "delegated"

    async def delete_session(self, session_id: str) -> str:
        self.calls.append("delete_session")
        return "delegated"

    async def chat_with_session(
        self,
        session_id: str,
        request: SessionChatRequest,
    ) -> str:
        self.calls.append("chat_with_session")
        return "delegated"

    async def start_agent_run_for_session(
        self,
        session_id: str,
        request: SessionAgentRunRequest,
    ) -> str:
        self.calls.append("start_agent_run_for_session")
        return "delegated"
