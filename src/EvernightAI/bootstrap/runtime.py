from datetime import datetime, timedelta, timezone
from pathlib import Path

from EvernightAI.core.domain.context import (
    ApproximateContextTokenEstimator,
    BasicContextStrategy,
    ContextManager,
    ContextOrganizer,
    ContextRegister,
    SummarizingContextStrategy,
    TokenBudgetContextStrategy,
    WindowTrimmingContextStrategy,
)
from EvernightAI.core.domain.data_analysis import (
    DataAnalysisManager,
    DataAnalysisRegister,
)
from EvernightAI.core.domain.memory import (
    BasicMemoryStrategy,
    BasicMemoryWriteStrategy,
    MemoryManager,
    MemoryRegister,
)
from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.core.domain.session import SessionManager, SessionRegister
from EvernightAI.core.domain.skill import SkillManager, SkillRegister
from EvernightAI.core.domain.tool import (
    BasicToolSafetyPolicy,
    ToolManager,
    ToolRegister,
)
from EvernightAI.core.protocol.agent import (
    AgentRunExecutorProtocol,
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
)
from EvernightAI.core.protocol.provider import ProviderConfigStoreProtocol
from EvernightAI.core.schema.agent import (
    AgentRunStatus,
    AgentTraceEvent,
    AgentTraceEventType,
)
from EvernightAI.core.protocol.context import (
    ContextOrganizerProtocol,
    ContextRegisterProtocol,
    ContextStrategyProtocol,
    ContextSummarizerProtocol,
    ContextTokenEstimatorProtocol,
)
from EvernightAI.core.protocol.data_analysis import (
    DataAnalysisManageProtocol,
    DataAnalysisRegisterProtocol,
)
from EvernightAI.core.protocol.memory import (
    MemoryRegisterProtocol,
)
from EvernightAI.core.protocol.sandbox import SandboxExecuteProtocol
from EvernightAI.core.protocol.session import (
    SessionManageProtocol,
    SessionRegisterProtocol,
)
from EvernightAI.core.protocol.skill import SkillManageProtocol, SkillRegisterProtocol
from EvernightAI.core.protocol.tool import (
    ToolRegisterProtocol,
    ToolSafetyPolicyProtocol,
)
from EvernightAI.infra.adapters.agent.sqlite import (
    SQLiteAgentRunStateRegister,
    SQLiteAgentTraceRegister,
)
from EvernightAI.infra.adapters.agent.executor import SingleProcessAgentRunExecutor
from EvernightAI.infra.adapters.context.sqlite import SQLiteContextRegister
from EvernightAI.infra.adapters.memory.sqlite import SQLiteMemoryRegister
from EvernightAI.infra.adapters.sandbox.bubblewrap import BubblewrapSandboxExecutor
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor
from EvernightAI.infra.adapters.session.sqlite import SQLiteSessionRegister
from EvernightAI.infra.adapters.providers.secrets import (
    EnvironmentProviderSecretResolver,
)
from EvernightAI.infra.adapters.providers.sqlite import SQLiteProviderConfigStore
from EvernightAI.infra.sqlite import SQLiteMigrationRunner
from EvernightAI.infra.registrations.provider.anthropic import (
    register_anthropic_provider,
)
from EvernightAI.infra.registrations.provider.gemini import register_gemini_provider
from EvernightAI.infra.registrations.provider.openai_compatible import (
    register_openai_compatible_provider,
)
from EvernightAI.infra.registrations.provider.openai_responses import (
    register_openai_responses_provider,
)
from EvernightAI.infra.registrations.data_analysis.runtime_sqlite import (
    register_sqlite_runtime_data_analysis_sources,
)
from EvernightAI.infra.registrations.skill.echo import register_echo_skill
from EvernightAI.infra.registrations.tool.restricted_filesystem import (
    register_restricted_filesystem_tools,
)
from EvernightAI.infra.registrations.tool.restricted_git import (
    register_restricted_git_tools,
)
from EvernightAI.infra.registrations.tool.restricted_project import (
    register_restricted_project_tools,
)
from EvernightAI.infra.registrations.tool.restricted_shell import (
    register_restricted_shell_tool,
)
from EvernightAI.infra.registrations.tool.restricted_web import (
    register_restricted_web_tools,
)
from EvernightAI.infra.registrations.tool.runtime_data import (
    register_runtime_data_tools,
)


def create_provider_factory() -> ProviderFactory:
    factory = ProviderFactory()
    register_openai_compatible_provider(factory)
    register_openai_responses_provider(factory)
    register_gemini_provider(factory)
    register_anthropic_provider(factory)
    return factory


def create_provider_manager() -> ProviderManager:
    return ProviderManager(create_provider_factory())


def create_tool_register() -> ToolRegister:
    return ToolRegister()


def create_tool_safety_policy() -> BasicToolSafetyPolicy:
    return BasicToolSafetyPolicy()


def create_sandbox_executor() -> SubprocessSandboxExecutor:
    return SubprocessSandboxExecutor()


def create_bubblewrap_sandbox_executor() -> BubblewrapSandboxExecutor:
    return BubblewrapSandboxExecutor()


def create_tool_manager(
    register: ToolRegisterProtocol | None = None,
    safety_policy: ToolSafetyPolicyProtocol | None = None,
) -> ToolManager:
    return ToolManager(
        register or create_tool_register(),
        safety_policy or create_tool_safety_policy(),
    )


def create_skill_register() -> SkillRegister:
    return SkillRegister()


def create_skill_manager(
    register: SkillRegisterProtocol | None = None,
) -> SkillManager:
    return SkillManager(register or create_skill_register())


def register_builtin_skills(register: SkillRegisterProtocol) -> None:
    register_echo_skill(register)


def register_builtin_tools(
    register: ToolRegisterProtocol,
    *,
    filesystem_root: str | Path | None = None,
    max_read_chars: int = 12000,
    max_directory_entries: int = 100,
    max_search_results: int = 100,
    allow_file_overwrite: bool = False,
    shell_allowed_commands: set[str] | None = None,
    shell_blocked_commands: set[str] | None = None,
    shell_working_directory: str | Path | None = None,
    shell_timeout_seconds: float = 10.0,
    shell_max_output_chars: int = 12000,
    shell_requires_approval: bool = True,
    shell_allowed_env_keys: set[str] | None = None,
    web_allowed_hosts: set[str] | None = None,
    web_download_directory: str | Path | None = None,
    web_timeout_seconds: float = 10.0,
    web_max_response_chars: int = 12000,
    web_max_download_bytes: int = 10_000_000,
    web_enabled: bool = False,
    git_repository_directory: str | Path | None = None,
    git_timeout_seconds: float = 10.0,
    git_max_output_chars: int = 12000,
    project_working_directory: str | Path | None = None,
    project_commands: dict[str, list[str]] | None = None,
    project_command_overrides: dict[str, dict[str, list[str]]] | None = None,
    project_directories: dict[str, str | Path] | None = None,
    project_timeout_seconds: float = 120.0,
    project_max_output_chars: int = 20000,
    sandbox: SandboxExecuteProtocol | None = None,
) -> None:
    if filesystem_root is not None:
        register_restricted_filesystem_tools(
            register,
            root_directory=filesystem_root,
            max_read_chars=max_read_chars,
            max_directory_entries=max_directory_entries,
            max_search_results=max_search_results,
            allow_overwrite=allow_file_overwrite,
            project_directories=project_directories,
        )

    if shell_allowed_commands is not None:
        register_restricted_shell_tool(
            register,
            allowed_commands=shell_allowed_commands,
            blocked_commands=shell_blocked_commands,
            working_directory=shell_working_directory or Path.cwd(),
            timeout_seconds=shell_timeout_seconds,
            max_output_chars=shell_max_output_chars,
            requires_approval=shell_requires_approval,
            allowed_env_keys=shell_allowed_env_keys,
            sandbox=sandbox,
        )

    if web_enabled:
        register_restricted_web_tools(
            register,
            allowed_hosts=web_allowed_hosts,
            download_directory=web_download_directory,
            timeout_seconds=web_timeout_seconds,
            max_response_chars=web_max_response_chars,
            max_download_bytes=web_max_download_bytes,
        )

    if git_repository_directory is not None:
        register_restricted_git_tools(
            register,
            repository_directory=git_repository_directory,
            timeout_seconds=git_timeout_seconds,
            max_output_chars=git_max_output_chars,
        )

    if project_working_directory is not None and project_commands is not None:
        register_restricted_project_tools(
            register,
            working_directory=project_working_directory,
            commands=project_commands,
            project_commands=project_command_overrides,
            project_directories=project_directories,
            timeout_seconds=project_timeout_seconds,
            max_output_chars=project_max_output_chars,
            sandbox=sandbox,
        )


def create_context_register() -> ContextRegister:
    return ContextRegister()


def create_context_manager(
    register: ContextRegisterProtocol | None = None,
) -> ContextManager:
    return ContextManager(register or create_context_register())


def create_context_organizer() -> ContextOrganizer:
    return ContextOrganizer()


def create_context_strategy(
    organizer: ContextOrganizerProtocol | None = None,
    *,
    max_messages: int | None = None,
    max_tokens: int | None = None,
    estimator: ContextTokenEstimatorProtocol | None = None,
    enable_summary: bool = False,
    summarizer: ContextSummarizerProtocol | None = None,
    summarize_after_messages: int = 100,
    keep_recent_messages: int = 20,
) -> ContextStrategyProtocol:
    strategy: ContextStrategyProtocol = BasicContextStrategy(
        organizer or create_context_organizer()
    )
    if enable_summary:
        if summarizer is None:
            raise ValueError("context summary requires a summarizer")
        strategy = SummarizingContextStrategy(
            strategy,
            summarizer,
            summarize_after_messages=summarize_after_messages,
            keep_recent_messages=keep_recent_messages,
        )
    if max_messages is not None:
        strategy = WindowTrimmingContextStrategy(
            strategy,
            max_messages=max_messages,
        )
    if max_tokens is not None:
        strategy = TokenBudgetContextStrategy(
            strategy,
            max_tokens=max_tokens,
            estimator=estimator or ApproximateContextTokenEstimator(),
        )
    return strategy


def create_memory_register() -> MemoryRegister:
    return MemoryRegister()


def create_data_analysis_register() -> DataAnalysisRegister:
    return DataAnalysisRegister()


def create_data_analysis_manager(
    register: DataAnalysisRegisterProtocol | None = None,
) -> DataAnalysisManager:
    return DataAnalysisManager(register or create_data_analysis_register())


def create_memory_manager(
    register: MemoryRegisterProtocol | None = None,
) -> MemoryManager:
    return MemoryManager(register or create_memory_register())


def create_memory_strategy() -> BasicMemoryStrategy:
    return BasicMemoryStrategy()


def create_memory_write_strategy() -> BasicMemoryWriteStrategy:
    return BasicMemoryWriteStrategy()


def create_session_register() -> SessionRegister:
    return SessionRegister()


def create_session_manager(
    register: SessionRegisterProtocol | None = None,
) -> SessionManager:
    return SessionManager(register or create_session_register())


def create_sqlite_context_register(database_path: str | Path) -> SQLiteContextRegister:
    return SQLiteContextRegister(database_path)


def create_sqlite_context_manager(database_path: str | Path) -> ContextManager:
    return ContextManager(create_sqlite_context_register(database_path))


def create_sqlite_memory_register(database_path: str | Path) -> SQLiteMemoryRegister:
    return SQLiteMemoryRegister(database_path)


def create_sqlite_memory_manager(database_path: str | Path) -> MemoryManager:
    return MemoryManager(create_sqlite_memory_register(database_path))


def create_sqlite_session_register(database_path: str | Path) -> SQLiteSessionRegister:
    return SQLiteSessionRegister(database_path)


def create_sqlite_session_manager(database_path: str | Path) -> SessionManager:
    return SessionManager(create_sqlite_session_register(database_path))


def create_sqlite_agent_state_register(
    database_path: str | Path,
) -> SQLiteAgentRunStateRegister:
    return SQLiteAgentRunStateRegister(database_path)


def create_sqlite_agent_trace_register(
    database_path: str | Path,
) -> SQLiteAgentTraceRegister:
    return SQLiteAgentTraceRegister(database_path)


def create_sqlite_provider_config_store(
    database_path: str | Path,
) -> SQLiteProviderConfigStore:
    return SQLiteProviderConfigStore(database_path)


def create_runtime() -> RuntimeKernel:
    return _create_runtime(
        context_register=create_context_register(),
        memory_register=create_memory_register(),
        session_register=create_session_register(),
    )


def create_runtime_with_agent_storage(
    *,
    agent_state_register: AgentRunStateRegisterProtocol,
    agent_trace_register: AgentTraceRegisterProtocol,
) -> RuntimeKernel:
    return _create_runtime(
        context_register=create_context_register(),
        memory_register=create_memory_register(),
        session_register=create_session_register(),
        agent_state_register=agent_state_register,
        agent_trace_register=agent_trace_register,
    )


def create_sqlite_runtime(
    database_path: str | Path,
    *,
    sandbox: SandboxExecuteProtocol | None = None,
    include_agent_storage: bool = True,
    filesystem_root: str | Path | None = None,
    max_read_chars: int = 12000,
    max_directory_entries: int = 100,
    max_search_results: int = 100,
    allow_file_overwrite: bool = False,
    shell_allowed_commands: set[str] | None = None,
    shell_blocked_commands: set[str] | None = None,
    shell_working_directory: str | Path | None = None,
    shell_timeout_seconds: float = 10.0,
    shell_max_output_chars: int = 12000,
    shell_requires_approval: bool = True,
    shell_allowed_env_keys: set[str] | None = None,
    web_enabled: bool = False,
    web_allowed_hosts: set[str] | None = None,
    web_download_directory: str | Path | None = None,
    web_timeout_seconds: float = 10.0,
    web_max_response_chars: int = 12000,
    web_max_download_bytes: int = 10_000_000,
    git_repository_directory: str | Path | None = None,
    git_timeout_seconds: float = 10.0,
    git_max_output_chars: int = 12000,
    project_working_directory: str | Path | None = None,
    project_commands: dict[str, list[str]] | None = None,
    project_command_overrides: dict[str, dict[str, list[str]]] | None = None,
    project_directories: dict[str, str | Path] | None = None,
    project_timeout_seconds: float = 120.0,
    project_max_output_chars: int = 20000,
    runtime_data_tools_enabled: bool = False,
    trace_retention_days: int | None = 30,
    trace_max_events: int | None = 100_000,
    context_max_messages: int | None = None,
    context_max_tokens: int | None = None,
    context_token_estimator: ContextTokenEstimatorProtocol | None = None,
    context_enable_summary: bool = False,
    context_summarizer: ContextSummarizerProtocol | None = None,
    context_summarize_after_messages: int = 100,
    context_keep_recent_messages: int = 20,
) -> RuntimeKernel:
    SQLiteMigrationRunner(database_path).run()
    sandbox = sandbox or create_sandbox_executor()
    tool_register = create_tool_register()
    register_builtin_tools(
        tool_register,
        filesystem_root=filesystem_root,
        max_read_chars=max_read_chars,
        max_directory_entries=max_directory_entries,
        max_search_results=max_search_results,
        allow_file_overwrite=allow_file_overwrite,
        shell_allowed_commands=shell_allowed_commands,
        shell_blocked_commands=shell_blocked_commands,
        shell_working_directory=shell_working_directory,
        shell_timeout_seconds=shell_timeout_seconds,
        shell_max_output_chars=shell_max_output_chars,
        shell_requires_approval=shell_requires_approval,
        shell_allowed_env_keys=shell_allowed_env_keys,
        web_enabled=web_enabled,
        web_allowed_hosts=web_allowed_hosts,
        web_download_directory=web_download_directory,
        web_timeout_seconds=web_timeout_seconds,
        web_max_response_chars=web_max_response_chars,
        web_max_download_bytes=web_max_download_bytes,
        git_repository_directory=git_repository_directory,
        git_timeout_seconds=git_timeout_seconds,
        git_max_output_chars=git_max_output_chars,
        project_working_directory=project_working_directory,
        project_commands=project_commands,
        project_command_overrides=project_command_overrides,
        project_directories=project_directories,
        project_timeout_seconds=project_timeout_seconds,
        project_max_output_chars=project_max_output_chars,
        sandbox=sandbox,
    )

    agent_state_register: AgentRunStateRegisterProtocol | None = None
    agent_trace_register: AgentTraceRegisterProtocol | None = None
    agent_run_executor: AgentRunExecutorProtocol | None = None
    if include_agent_storage:
        agent_state_register = create_sqlite_agent_state_register(database_path)
        agent_trace_register = create_sqlite_agent_trace_register(database_path)
        recover_interrupted_agent_runs(agent_state_register, agent_trace_register)
        older_than = (
            (datetime.now(timezone.utc) - timedelta(days=trace_retention_days)).isoformat()
            if trace_retention_days is not None
            else None
        )
        agent_trace_register.prune_events(
            older_than=older_than,
            keep_latest=trace_max_events,
        )
        agent_run_executor = SingleProcessAgentRunExecutor(agent_state_register)
    data_analysis_register = create_data_analysis_register()
    register_sqlite_runtime_data_analysis_sources(
        data_analysis_register,
        database_path=database_path,
        include_agent_sources=include_agent_storage,
    )

    return _create_runtime(
        tool_register=tool_register,
        context_register=create_sqlite_context_register(database_path),
        memory_register=create_sqlite_memory_register(database_path),
        session_register=create_sqlite_session_register(database_path),
        provider_config_store=create_sqlite_provider_config_store(database_path),
        data_analysis_register=data_analysis_register,
        agent_state_register=agent_state_register,
        agent_trace_register=agent_trace_register,
        agent_run_executor=agent_run_executor,
        runtime_data_tools_enabled=runtime_data_tools_enabled,
        sandbox=sandbox,
        context_max_messages=context_max_messages,
        context_max_tokens=context_max_tokens,
        context_token_estimator=context_token_estimator,
        context_enable_summary=context_enable_summary,
        context_summarizer=context_summarizer,
        context_summarize_after_messages=context_summarize_after_messages,
        context_keep_recent_messages=context_keep_recent_messages,
    )


def _create_runtime(
    *,
    tool_register: ToolRegisterProtocol | None = None,
    tool_safety_policy: ToolSafetyPolicyProtocol | None = None,
    context_register: ContextRegisterProtocol,
    memory_register: MemoryRegisterProtocol,
    session_register: SessionRegisterProtocol,
    provider_config_store: ProviderConfigStoreProtocol | None = None,
    data_analysis_register: DataAnalysisRegisterProtocol | None = None,
    data_analysis: DataAnalysisManageProtocol | None = None,
    sessions: SessionManageProtocol | None = None,
    skill_register: SkillRegisterProtocol | None = None,
    skills: SkillManageProtocol | None = None,
    agent_state_register: AgentRunStateRegisterProtocol | None = None,
    agent_trace_register: AgentTraceRegisterProtocol | None = None,
    agent_run_executor: AgentRunExecutorProtocol | None = None,
    runtime_data_tools_enabled: bool = False,
    sandbox: SandboxExecuteProtocol | None = None,
    context_max_messages: int | None = None,
    context_max_tokens: int | None = None,
    context_token_estimator: ContextTokenEstimatorProtocol | None = None,
    context_enable_summary: bool = False,
    context_summarizer: ContextSummarizerProtocol | None = None,
    context_summarize_after_messages: int = 100,
    context_keep_recent_messages: int = 20,
) -> RuntimeKernel:
    provider_factory = create_provider_factory()
    providers = ProviderManager(
        provider_factory,
        config_store=provider_config_store,
        secret_resolver=EnvironmentProviderSecretResolver(),
    )
    tool_register = tool_register or create_tool_register()
    tool_safety_policy = tool_safety_policy or create_tool_safety_policy()
    sandbox = sandbox or create_sandbox_executor()
    tools = ToolManager(tool_register, tool_safety_policy)
    skill_register = skill_register or create_skill_register()
    register_builtin_skills(skill_register)
    skills = skills or create_skill_manager(skill_register)
    contexts = ContextManager(context_register)
    context_organizer = create_context_organizer()
    context_strategy = create_context_strategy(
        context_organizer,
        max_messages=context_max_messages,
        max_tokens=context_max_tokens,
        estimator=context_token_estimator,
        enable_summary=context_enable_summary,
        summarizer=context_summarizer,
        summarize_after_messages=context_summarize_after_messages,
        keep_recent_messages=context_keep_recent_messages,
    )
    data_analysis_register = data_analysis_register or create_data_analysis_register()
    data_analysis = data_analysis or create_data_analysis_manager(data_analysis_register)
    memories = MemoryManager(memory_register)
    memory_strategy = create_memory_strategy()
    memory_write_strategy = create_memory_write_strategy()
    sessions = sessions or create_session_manager(session_register)
    if runtime_data_tools_enabled:
        register_runtime_data_tools(
            tool_register,
            contexts=contexts,
            memories=memories,
            sessions=sessions,
        )

    return RuntimeKernel(
        provider_factory=provider_factory,
        providers=providers,
        provider_config_store=provider_config_store,
        tool_register=tool_register,
        tools=tools,
        tool_safety_policy=tool_safety_policy,
        sandbox=sandbox,
        skill_register=skill_register,
        skills=skills,
        context_register=context_register,
        contexts=contexts,
        context_organizer=context_organizer,
        context_strategy=context_strategy,
        data_analysis_register=data_analysis_register,
        data_analysis=data_analysis,
        memory_register=memory_register,
        memories=memories,
        memory_strategy=memory_strategy,
        memory_write_strategy=memory_write_strategy,
        session_register=session_register,
        sessions=sessions,
        agent_state_register=agent_state_register,
        agent_trace_register=agent_trace_register,
        agent_run_executor=agent_run_executor,
    )


def recover_interrupted_agent_runs(
    state_register: AgentRunStateRegisterProtocol,
    trace_register: AgentTraceRegisterProtocol,
) -> int:
    recovered = 0
    for state in state_register.query_states(status=AgentRunStatus.RUNNING):
        event = AgentTraceEvent(
            event_type=AgentTraceEventType.RUN_PAUSED,
            summary="Agent run paused: runtime restart",
            metadata={"reason": "interrupted", "source": "runtime_restart"},
        )
        event.sequence = trace_register.append_event(state.run_id, event)
        state.status = AgentRunStatus.PAUSED
        state.stop_reason = None
        state.trace.append(event)
        state.metadata = {
            **state.metadata,
            "interrupted": True,
            "interruption_reason": "runtime_restart",
        }
        state_register.save_state(state)
        recovered += 1
    return recovered
