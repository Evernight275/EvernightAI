from pathlib import Path

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime
from EvernightAI.cli import main as package_main
from EvernightAI.core.error.provider import ProviderUnavailableError
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
    AgentTraceEvent,
    AgentTraceEventType,
)
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.memory import MemoryItem, MemorySelection
from EvernightAI.core.schema.provider import ProviderConfig
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
    SessionChatResult,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillDefinition,
    SkillRenderRequest,
)
from EvernightAI.core.schema.tool import ToolApprovalDecision
from EvernightAI.entrypoint.cli import main as entrypoint_main


def test_entrypoint_cli_config_check_prints_summary(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[provider.main]
name = "Main"
type = "openai"
""".strip(),
        encoding="utf-8",
    )

    exit_code = entrypoint_main(["config", "check", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Config OK" in captured.out
    assert "providers: 1" in captured.out


def test_package_cli_wrapper_prints_redacted_config_json(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[provider.main]
name = "Main"
type = "openai"
api_key = "secret-key"
""".strip(),
        encoding="utf-8",
    )

    exit_code = package_main(["config", "show", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"api_key": "***"' in captured.out
    assert "secret-key" not in captured.out


def test_entrypoint_cli_serve_uses_server_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    calls = []

    monkeypatch.setattr(
        "EvernightAI.entrypoint.cli.serve_http",
        lambda config: calls.append(config),
    )

    exit_code = entrypoint_main(["serve", "--config", str(config_path)])

    assert exit_code == 0
    assert calls == [str(config_path)]


def test_entrypoint_cli_skill_commands(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "EvernightAI.entrypoint.cli.create_interface_from_config",
        lambda _config: create_skill_interface(),
    )

    assert entrypoint_main(["skill", "list", "--config", str(config_path)]) == 0
    list_output = capsys.readouterr().out
    assert "summarize" in list_output

    assert (
        entrypoint_main(
            ["skill", "show", "summarize", "--config", str(config_path)]
        )
        == 0
    )
    show_output = capsys.readouterr().out
    assert '"name": "summarize"' in show_output

    assert (
        entrypoint_main(
            [
                "skill",
                "supports",
                "summarize",
                "--capability",
                "chat",
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    supports_output = capsys.readouterr().out
    assert supports_output.strip() == "yes"

    assert (
        entrypoint_main(
            [
                "skill",
                "render",
                "summarize",
                "--vars-json",
                '{"text": "hello"}',
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    render_output = capsys.readouterr().out
    assert '"render_id": "summarize-0"' in render_output
    assert '"text": "hello"' in render_output


def test_entrypoint_cli_reports_missing_config_without_traceback(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "missing.toml"

    exit_code = entrypoint_main(["config", "check", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "error: ConfigurationError: Config file not found" in captured.err
    assert "Traceback" not in captured.err


def test_entrypoint_cli_reports_invalid_toml_without_traceback(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[provider.main", encoding="utf-8")

    exit_code = entrypoint_main(["config", "check", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "error: ConfigurationError: Invalid TOML config" in captured.err
    assert "Traceback" not in captured.err


def test_entrypoint_cli_reports_invalid_skill_vars_json(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "EvernightAI.entrypoint.cli.create_interface_from_config",
        lambda _config: create_skill_interface(),
    )

    exit_code = entrypoint_main(
        [
            "skill",
            "render",
            "summarize",
            "--vars-json",
            "[]",
            "--config",
            str(config_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "error: ConfigurationError: Expected a JSON object" in captured.err
    assert "Traceback" not in captured.err


def test_entrypoint_cli_reports_provider_errors_without_traceback(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[provider.main]
name = "Main"
type = "openai"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "EvernightAI.entrypoint.cli.create_interface_from_config",
        lambda _config: FailingChatInterface(),
    )

    exit_code = entrypoint_main(
        [
            "chat",
            "--provider",
            "main",
            "--model",
            "model-1",
            "--config",
            str(config_path),
            "hello",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "error: ProviderUnavailableError: provider chat failed" in captured.err
    assert "Traceback" not in captured.err


def test_entrypoint_cli_context_memory_session_and_agent_run_commands(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    interface = FakeOperationsInterface()

    monkeypatch.setattr(
        "EvernightAI.entrypoint.cli.create_interface_from_config",
        lambda _config: interface,
    )

    assert (
        entrypoint_main(
            [
                "context",
                "create",
                "--json",
                '{"context_id": "ctx-1"}',
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    assert '"context_id": "ctx-1"' in capsys.readouterr().out

    assert (
        entrypoint_main(
            [
                "context",
                "append",
                "ctx-1",
                "--message-json",
                '{"role": "user", "content": [{"type": "text", "text": "hello"}]}',
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    assert '"text": "hello"' in capsys.readouterr().out

    assert entrypoint_main(["context", "list", "--config", str(config_path)]) == 0
    assert "ctx-1" in capsys.readouterr().out

    assert (
        entrypoint_main(
            [
                "memory",
                "create",
                "--json",
                '{"memory_id": "mem-1", "content": "Use short answers"}',
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    assert '"memory_id": "mem-1"' in capsys.readouterr().out

    assert (
        entrypoint_main(
            [
                "memory",
                "select",
                "--query-json",
                '{"limit": 1}',
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    assert '"memories"' in capsys.readouterr().out

    assert (
        entrypoint_main(
            [
                "session",
                "create",
                "--json",
                (
                    '{"session_id": "session-1", "context_id": "ctx-1", '
                    '"provider_id": "provider-1", "model_id": "model-1"}'
                ),
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    assert '"session_id": "session-1"' in capsys.readouterr().out

    assert (
        entrypoint_main(
            [
                "session",
                "chat",
                "session-1",
                "--request-json",
                '{"messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]}',
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    assert '"response"' in capsys.readouterr().out

    assert (
        entrypoint_main(
            [
                "session",
                "agent-run",
                "session-1",
                "--request-json",
                '{"messages": []}',
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    assert '"run_id": "session-run-1"' in capsys.readouterr().out

    assert (
        entrypoint_main(
            [
                "agent-run",
                "start",
                "--request-json",
                (
                    '{"provider_id": "provider-1", "context_id": "ctx-1", '
                    '"model_id": "model-1", "metadata": {"run_id": "run-1"}}'
                ),
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    assert '"run_id": "run-1"' in capsys.readouterr().out

    assert entrypoint_main(["agent-run", "list", "--config", str(config_path)]) == 0
    assert "run-1" in capsys.readouterr().out

    assert (
        entrypoint_main(["agent-run", "trace", "run-1", "--config", str(config_path)])
        == 0
    )
    assert '"event_type": "run_started"' in capsys.readouterr().out

    assert (
        entrypoint_main(
            [
                "agent-run",
                "resume",
                "run-1",
                "--approvals-json",
                "[]",
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    assert '"status": "finished"' in capsys.readouterr().out


def test_entrypoint_cli_runtime_command_requires_cli_auth(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[auth]
enabled = true
""".strip(),
        encoding="utf-8",
    )

    exit_code = entrypoint_main(["context", "list", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "AuthRequiredError" in captured.err


def test_entrypoint_cli_runtime_command_checks_permissions(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[auth]
enabled = true

[auth.principal.reader]
api_key = "secret"
permissions = ["contexts:list"]
""".strip(),
        encoding="utf-8",
    )

    exit_code = entrypoint_main(
        [
            "context",
            "create",
            "--json",
            '{"context_id": "ctx-1"}',
            "--config",
            str(config_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "AuthPermissionDeniedError" in captured.err


def test_entrypoint_cli_runtime_command_uses_configured_cli_principal(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[runtime]
database_path = "{(tmp_path / "runtime.sqlite3").as_posix()}"

[auth]
enabled = true

[auth.principal.writer]
api_key = "secret"
permissions = ["contexts:create"]
""".strip(),
        encoding="utf-8",
    )

    exit_code = entrypoint_main(
        [
            "context",
            "create",
            "--json",
            '{"context_id": "ctx-1"}',
            "--config",
            str(config_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"context_id": "ctx-1"' in captured.out


def create_skill_interface():
    async def summarize(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(
            render_id=request.render_id,
            skill_name=request.skill_name,
            messages=[
                Content(
                    role=MessageRole.SYSTEM,
                    content=[
                        ContentPart(
                            type=ContentPartType.TEXT,
                            text=str(request.variables["text"]),
                        )
                    ],
                )
            ],
        )

    runtime = create_runtime()
    runtime.skill_register.register(
        SkillDefinition(
            name="summarize",
            description="Summarize text",
            capabilities=[SkillCapability.CHAT],
        ),
        summarize,
    )
    return create_interface(runtime)


class FailingChatInterface:
    def __init__(self) -> None:
        self.chat = FailingChatCommand()

    async def close(self) -> None:
        pass


class FailingChatCommand:
    async def create_provider(
        self,
        _config: ProviderConfig,
    ) -> ProviderInstanceProtocol:
        return FailingProvider()

    async def chat(
        self,
        _provider_id: str,
        _request: ChatRequest,
    ) -> ChatResponse:
        raise ProviderUnavailableError("provider chat failed")


class FailingProvider(ProviderInstanceProtocol):
    pass


class FakeOperationsInterface:
    def __init__(self) -> None:
        self.chat = FakeChatOperations()
        self.agent_runs = FakeAgentRunOperations()
        self.sessions = FakeSessionOperations(self.agent_runs)

    async def close(self) -> None:
        pass


class FakeChatOperations:
    def __init__(self) -> None:
        self.contexts: dict[str, Context] = {}
        self.memories: dict[str, MemoryItem] = {}

    async def create_context(self, context: Context) -> Context:
        self.contexts[context.context_id] = context
        return context

    async def get_context(self, context_id: str) -> Context:
        return self.contexts[context_id]

    async def list_contexts(self) -> list[Context]:
        return list(self.contexts.values())

    async def append_context(self, context_id: str, message: Content) -> Context:
        context = self.contexts[context_id]
        updated = context.model_copy(
            update={"messages": [*context.messages, message]}
        )
        self.contexts[context_id] = updated
        return updated

    async def replace_context(self, context: Context) -> Context:
        self.contexts[context.context_id] = context
        return context

    async def delete_context(self, context_id: str) -> None:
        del self.contexts[context_id]

    async def create_memory(self, memory: MemoryItem) -> MemoryItem:
        self.memories[memory.memory_id] = memory
        return memory

    async def get_memory(self, memory_id: str) -> MemoryItem:
        return self.memories[memory_id]

    async def list_memories(self) -> list[MemoryItem]:
        return list(self.memories.values())

    async def select_memories(self, _query) -> MemorySelection:
        return MemorySelection(memories=list(self.memories.values()))

    async def delete_memory(self, memory_id: str) -> None:
        del self.memories[memory_id]


class FakeSessionOperations:
    def __init__(self, agent_runs: "FakeAgentRunOperations") -> None:
        self._agent_runs = agent_runs
        self.sessions: dict[str, Session] = {}

    async def create_session(self, session: Session) -> Session:
        self.sessions[session.session_id] = session
        return session

    async def get_session(self, session_id: str) -> Session:
        return self.sessions[session_id]

    async def replace_session(self, session: Session) -> Session:
        self.sessions[session.session_id] = session
        return session

    async def archive_session(self, session_id: str) -> Session:
        session = self.sessions[session_id].model_copy(update={"status": "archived"})
        self.sessions[session_id] = session
        return session

    async def list_sessions(self) -> list[Session]:
        return list(self.sessions.values())

    async def delete_session(self, session_id: str) -> None:
        del self.sessions[session_id]

    async def chat_with_session(
        self,
        session_id: str,
        _request: SessionChatRequest,
    ) -> SessionChatResult:
        session = self.sessions[session_id]
        return SessionChatResult(
            session=session,
            response=ChatResponse(
                model_id=session.model_id or "model-1",
                message=Content(
                    role=MessageRole.ASSISTANT,
                    content=[ContentPart(type=ContentPartType.TEXT, text="ok")],
                ),
            ),
        )

    async def start_agent_run_for_session(
        self,
        session_id: str,
        request: SessionAgentRunRequest,
    ) -> AgentRunState:
        session = self.sessions[session_id]
        agent_request = AgentRunRequest(
            provider_id=session.provider_id or "provider-1",
            context_id=session.context_id,
            model_id=session.model_id or "model-1",
            messages=request.messages,
            metadata={"run_id": f"{session_id.replace('session', 'session-run')}"},
        )
        return await self._agent_runs.start(agent_request)


class FakeAgentRunOperations:
    def __init__(self) -> None:
        self.states: dict[str, AgentRunState] = {}
        self.traces: dict[str, list[AgentTraceEvent]] = {}

    def list_states(self) -> list[AgentRunState]:
        return list(self.states.values())

    def get_state(self, run_id: str) -> AgentRunState:
        return self.states[run_id]

    def list_trace(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentTraceEvent]:
        events = [
            event
            for event in self.traces[run_id]
            if event.sequence is None or event.sequence > after_sequence
        ]
        return events if limit is None else events[:limit]

    async def start(self, request: AgentRunRequest) -> AgentRunState:
        run_id = str(request.metadata.get("run_id") or "run-1")
        state = AgentRunState(
            run_id=run_id,
            request=request,
            status=AgentRunStatus.PAUSED,
        )
        self.states[run_id] = state
        self.traces[run_id] = [
            AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED)
        ]
        return state

    async def resume(
        self,
        run_id: str,
        _approvals: list[ToolApprovalDecision],
    ) -> AgentRunState:
        state = self.states[run_id].model_copy(
            update={"status": AgentRunStatus.FINISHED}
        )
        self.states[run_id] = state
        self.traces[run_id].append(
            AgentTraceEvent(event_type=AgentTraceEventType.RUN_STOPPED)
        )
        return state
