import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from EvernightAI.application.agent import (
    latest_active_agent_run_lease,
    recover_interrupted_agent_runs,
)
from EvernightAI.application.image_task import ImageTaskApplication
from EvernightAI.application.image_tool import ImageToolApplication
from EvernightAI.bootstrap.options import (
    BuiltinToolOptions,
    ContextStrategyOptions,
)
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
from EvernightAI.core.domain.image_task import ImageTaskStore
from EvernightAI.core.domain.memory import (
    BasicMemoryStrategy,
    BasicMemoryWriteStrategy,
    DisabledMemoryStrategy,
    DisabledMemoryWriteStrategy,
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
from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.protocol.agent import (
    AgentRunExecutorProtocol,
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
    ToolExecutionRegisterProtocol,
)
from EvernightAI.core.protocol.context import (
    ContextOrganizerProtocol,
    ContextRegisterProtocol,
    ContextStrategyProtocol,
)
from EvernightAI.core.protocol.data_analysis import (
    DataAnalysisManageProtocol,
    DataAnalysisRegisterProtocol,
)
from EvernightAI.core.protocol.file import FileArtifactStoreProtocol
from EvernightAI.core.protocol.image import (
    ImageGenerationStoreProtocol,
    ImageTaskStoreProtocol,
)
from EvernightAI.core.protocol.memory import (
    MemoryRegisterProtocol,
    MemoryStrategyProtocol,
    MemoryWriteStrategyProtocol,
)
from EvernightAI.core.protocol.provider import (
    ProviderConfigStoreProtocol,
    ProviderSecretResolverProtocol,
)
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.protocol.sandbox import SandboxExecuteProtocol
from EvernightAI.core.protocol.session import (
    SessionManageProtocol,
    SessionRegisterProtocol,
)
from EvernightAI.core.protocol.skill import (
    SkillManageProtocol,
    SkillRegisterProtocol,
    SkillTemplateStoreProtocol,
)
from EvernightAI.core.protocol.tool import (
    ToolPolicyStoreProtocol,
    ToolRegisterProtocol,
    ToolSafetyPolicyProtocol,
    ToolSourceProtocol,
)
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.core.schema.content import PromptCacheMode, PromptCacheScope
from EvernightAI.core.schema.image_task import ImageTask
from EvernightAI.infra.adapters.agent.executor import SingleProcessAgentRunExecutor
from EvernightAI.infra.adapters.agent.sqlite import (
    SQLiteAgentRunStateRegister,
    SQLiteAgentTraceRegister,
    SQLiteToolExecutionRegister,
)
from EvernightAI.infra.adapters.context.sqlite import SQLiteContextRegister
from EvernightAI.infra.adapters.images.archive import PublicImageArchive
from EvernightAI.infra.adapters.images.executor import SingleProcessImageTaskExecutor
from EvernightAI.infra.adapters.images.sqlite import SQLiteImageGenerationStore
from EvernightAI.infra.adapters.images.tasks import SQLiteImageTaskStore
from EvernightAI.infra.adapters.memory.sqlite import SQLiteMemoryRegister
from EvernightAI.infra.adapters.providers.secrets import (
    EnvironmentProviderSecretResolver,
)
from EvernightAI.infra.adapters.providers.sqlite import SQLiteProviderConfigStore
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor
from EvernightAI.infra.adapters.session.sqlite import SQLiteSessionRegister
from EvernightAI.infra.adapters.skill.sqlite import SQLiteSkillTemplateStore
from EvernightAI.infra.adapters.skill.template import create_template_renderer
from EvernightAI.infra.adapters.tool.file_artifacts import SQLiteFileArtifactStore
from EvernightAI.infra.adapters.tool.sqlite import SQLiteToolPolicyStore
from EvernightAI.infra.adapters.tool.workspace_directory import WorkspaceDirectoryStore
from EvernightAI.infra.registrations.data_analysis.runtime_sqlite import (
    ensure_sqlite_runtime_data_analysis_views,
    register_sqlite_runtime_data_analysis_sources,
)
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
from EvernightAI.infra.registrations.skill.echo import register_echo_skill
from EvernightAI.infra.registrations.tool.display_file import register_display_file_tool
from EvernightAI.infra.registrations.tool.image import register_image_tool
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
from EvernightAI.infra.sqlite import SQLiteMigrationRunner

LOGGER = logging.getLogger(__name__)


def create_memory_strategy(name: str) -> MemoryStrategyProtocol:
    if name == "basic":
        return BasicMemoryStrategy()
    if name == "disabled":
        return DisabledMemoryStrategy()
    raise ConfigurationError(f"Unknown memory selection strategy: {name}")


def create_memory_write_strategy(name: str) -> MemoryWriteStrategyProtocol:
    if name == "basic":
        return BasicMemoryWriteStrategy()
    if name == "disabled":
        return DisabledMemoryWriteStrategy()
    raise ConfigurationError(f"Unknown memory write strategy: {name}")


class DeferredAgentRunRecovery:
    """Recheck interrupted runs while the runtime is alive."""

    def __init__(
        self,
        runtime: RuntimeProtocol,
        *,
        margin_seconds: float = 1.0,
        interval_seconds: float = 5.0,
    ) -> None:
        if interval_seconds <= 0 or margin_seconds < 0:
            raise ValueError(
                "Recovery intervals must be positive and margin nonnegative"
            )
        self._runtime = runtime
        self._margin_seconds = margin_seconds
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def _recover(self) -> None:
        states = self._runtime.agent_state_register
        traces = self._runtime.agent_trace_register
        if states is not None and traces is not None:
            recover_interrupted_agent_runs(
                states,
                traces,
                self._runtime.tool_execution_register,
                unleased_grace_seconds=30,
            )

    async def start(self) -> None:
        if self._task is not None:
            return
        if (
            self._runtime.agent_state_register is None
            or self._runtime.agent_trace_register is None
        ):
            return
        self._recover()
        self._task = asyncio.create_task(self._watch(), name="evernight-agent-recovery")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _watch(self) -> None:
        while True:
            try:
                states = self._runtime.agent_state_register
                expires_at = (
                    latest_active_agent_run_lease(states)
                    if states is not None
                    else None
                )
                delay = self._interval_seconds
                if expires_at is not None:
                    delay = min(
                        delay,
                        max(
                            0, (expires_at - datetime.now(timezone.utc)).total_seconds()
                        )
                        + self._margin_seconds,
                    )
                await asyncio.sleep(delay)
                self._recover()
            except Exception:
                LOGGER.exception("Agent run recovery failed; retrying")
                await asyncio.sleep(self._interval_seconds)


def create_provider_factory() -> ProviderFactory:
    factory = ProviderFactory()
    register_openai_compatible_provider(factory)
    register_openai_responses_provider(factory)
    register_gemini_provider(factory)
    register_anthropic_provider(factory)
    return factory


def create_skill_manager(
    register: SkillRegisterProtocol | None = None,
    template_store: SkillTemplateStoreProtocol | None = None,
) -> SkillManager:
    return SkillManager(
        register or SkillRegister(),
        template_factory=create_template_renderer,
        template_store=template_store,
    )


def register_builtin_tools(
    register: ToolRegisterProtocol,
    options: BuiltinToolOptions = BuiltinToolOptions(),
    *,
    file_artifacts: FileArtifactStoreProtocol | None = None,
    workspace_directories: WorkspaceDirectoryProtocol | None = None,
    sandbox: SandboxExecuteProtocol | None = None,
) -> None:
    project_directories = options.project_directories
    if (filesystem := options.filesystem) is not None:
        register_restricted_filesystem_tools(
            register,
            root_directory=filesystem.root,
            workspace_directories=workspace_directories,
            max_read_chars=filesystem.max_read_chars,
            max_directory_entries=filesystem.max_directory_entries,
            max_search_results=filesystem.max_search_results,
            allow_overwrite=filesystem.allow_overwrite,
            project_directories=project_directories,
        )
        if file_artifacts is not None:
            register_display_file_tool(
                register,
                root_directory=filesystem.root,
                store=file_artifacts,
                workspace_directories=workspace_directories,
            )

    if (shell := options.shell) is not None:
        register_restricted_shell_tool(
            register,
            allowed_commands=shell.allowed_commands,
            blocked_commands=shell.blocked_commands,
            working_directory=shell.working_directory or Path.cwd(),
            workspace_directories=workspace_directories,
            timeout_seconds=shell.timeout_seconds,
            max_output_chars=shell.max_output_chars,
            requires_approval=shell.requires_approval,
            relaxed_approval=shell.relaxed_approval,
            allowed_env_keys=shell.allowed_env_keys,
            sandbox=sandbox,
        )

    if (web := options.web) is not None:
        register_restricted_web_tools(
            register,
            allowed_hosts=web.allowed_hosts,
            download_directory=web.download_directory,
            timeout_seconds=web.timeout_seconds,
            max_response_chars=web.max_response_chars,
            max_download_bytes=web.max_download_bytes,
        )

    if (git := options.git) is not None:
        register_restricted_git_tools(
            register,
            repository_directory=git.repository_directory,
            workspace_directories=workspace_directories,
            project_directories=project_directories,
            timeout_seconds=git.timeout_seconds,
            max_output_chars=git.max_output_chars,
            sandbox=sandbox,
        )

    if (project := options.project) is not None:
        register_restricted_project_tools(
            register,
            working_directory=project.working_directory,
            workspace_directories=workspace_directories,
            commands=project.commands,
            project_commands=project.command_overrides,
            project_directories=project_directories,
            timeout_seconds=project.timeout_seconds,
            max_output_chars=project.max_output_chars,
            sandbox=sandbox,
        )


def create_context_strategy(
    organizer: ContextOrganizerProtocol | None = None,
    options: ContextStrategyOptions = ContextStrategyOptions(),
) -> ContextStrategyProtocol:
    strategy: ContextStrategyProtocol = BasicContextStrategy(
        organizer or ContextOrganizer()
    )
    if options.enable_summary:
        if options.summarizer is None:
            raise ValueError("context summary requires a summarizer")
        strategy = SummarizingContextStrategy(
            strategy,
            options.summarizer,
            summarize_after_messages=options.summarize_after_messages,
            keep_recent_messages=options.keep_recent_messages,
        )
    if options.max_messages is not None:
        strategy = WindowTrimmingContextStrategy(
            strategy,
            max_messages=options.max_messages,
        )
    if options.max_tokens is not None:
        strategy = TokenBudgetContextStrategy(
            strategy,
            max_tokens=options.max_tokens,
            estimator=options.estimator or ApproximateContextTokenEstimator(),
        )
    return strategy


def create_runtime(
    *,
    memory_strategy: MemoryStrategyProtocol | None = None,
    memory_write_strategy: MemoryWriteStrategyProtocol | None = None,
) -> RuntimeKernel:
    return _create_runtime(
        memory_strategy=memory_strategy,
        memory_write_strategy=memory_write_strategy,
        context_register=ContextRegister(),
        memory_register=MemoryRegister(),
        session_register=SessionRegister(),
    )


def create_runtime_with_agent_storage(
    *,
    memory_strategy: MemoryStrategyProtocol | None = None,
    memory_write_strategy: MemoryWriteStrategyProtocol | None = None,
    agent_state_register: AgentRunStateRegisterProtocol,
    agent_trace_register: AgentTraceRegisterProtocol,
    tool_execution_register: ToolExecutionRegisterProtocol | None = None,
) -> RuntimeKernel:
    return _create_runtime(
        memory_strategy=memory_strategy,
        memory_write_strategy=memory_write_strategy,
        context_register=ContextRegister(),
        memory_register=MemoryRegister(),
        session_register=SessionRegister(),
        agent_state_register=agent_state_register,
        agent_trace_register=agent_trace_register,
        tool_execution_register=tool_execution_register,
    )


def create_sqlite_runtime(
    database_path: str | Path,
    *,
    memory_strategy: MemoryStrategyProtocol | None = None,
    memory_write_strategy: MemoryWriteStrategyProtocol | None = None,
    startup_handlers: list[Callable[[], Awaitable[None]]] | None = None,
    tools: BuiltinToolOptions = BuiltinToolOptions(),
    context: ContextStrategyOptions = ContextStrategyOptions(),
    sandbox: SandboxExecuteProtocol | None = None,
    include_agent_storage: bool = True,
    workspace_directories: WorkspaceDirectoryProtocol | None = None,
    runtime_data_tools_enabled: bool = False,
    trace_retention_days: int | None = 30,
    trace_max_events: int | None = 100_000,
    prompt_cache_mode: PromptCacheMode = PromptCacheMode.PREFER_EXPLICIT,
    prompt_cache_scope: PromptCacheScope = PromptCacheScope.CONTEXT,
    tool_sources: list[ToolSourceProtocol] | None = None,
    configure_data_analysis: Callable[[DataAnalysisRegisterProtocol], None]
    | None = None,
) -> RuntimeKernel:
    opened: list[Any] = []
    try:
        if workspace_directories is None and tools.filesystem is not None:
            workspace_directories = WorkspaceDirectoryStore(
                tools.filesystem.root,
                browse_host_directories=True,
                database_path=database_path,
                protected_paths=[
                    *runtime_state_paths(database_path),
                    Path(sys.prefix),
                    Path(sys.base_prefix),
                ],
            )
            opened.append(workspace_directories)
        sandbox = sandbox or SubprocessSandboxExecutor()
        tool_register = ToolRegister()
        file_artifacts = _opened(opened, SQLiteFileArtifactStore(database_path))
        register_builtin_tools(
            tool_register,
            tools,
            file_artifacts=file_artifacts,
            workspace_directories=workspace_directories,
            sandbox=sandbox,
        )

        agent_state_register: AgentRunStateRegisterProtocol | None = None
        agent_trace_register: AgentTraceRegisterProtocol | None = None
        agent_run_executor: AgentRunExecutorProtocol | None = None
        tool_execution_register: ToolExecutionRegisterProtocol | None = None
        if include_agent_storage:
            agent_state_register = _opened(
                opened, SQLiteAgentRunStateRegister(database_path)
            )
            agent_trace_register = _opened(
                opened, SQLiteAgentTraceRegister(database_path)
            )
            tool_execution_register = _opened(
                opened, SQLiteToolExecutionRegister(database_path)
            )
            agent_run_executor = SingleProcessAgentRunExecutor(agent_state_register)
        data_analysis_register = _opened(opened, DataAnalysisRegister())
        register_sqlite_runtime_data_analysis_sources(
            data_analysis_register,
            database_path=database_path,
            include_agent_sources=include_agent_storage,
            ensure_views=False,
        )
        if configure_data_analysis is not None:
            configure_data_analysis(data_analysis_register)

        provider_config_store = _opened(
            opened, SQLiteProviderConfigStore(database_path)
        )

        async def startup() -> None:
            for handler in startup_handlers or []:
                await handler()
            SQLiteMigrationRunner(database_path).run()
            ensure_sqlite_runtime_data_analysis_views(
                database_path, include_agent_sources=include_agent_storage
            )
            await recovery.start()
            if agent_trace_register is not None:
                older_than = (
                    (
                        datetime.now(timezone.utc)
                        - timedelta(days=trace_retention_days)
                    ).isoformat()
                    if trace_retention_days is not None
                    else None
                )
                if older_than is not None or trace_max_events is not None:
                    agent_trace_register.prune_events(
                        older_than=older_than, keep_latest=trace_max_events
                    )

        async def shutdown() -> None:
            await recovery.close()

        runtime = _create_runtime(
            memory_strategy=memory_strategy,
            memory_write_strategy=memory_write_strategy,
            startup_handlers=[startup],
            shutdown_handlers=[shutdown],
            tool_register=tool_register,
            tool_sources=tool_sources,
            context_register=_opened(opened, SQLiteContextRegister(database_path)),
            memory_register=_opened(opened, SQLiteMemoryRegister(database_path)),
            session_register=_opened(opened, SQLiteSessionRegister(database_path)),
            provider_config_store=provider_config_store,
            provider_secret_resolver=provider_config_store,
            skill_template_store=_opened(
                opened, SQLiteSkillTemplateStore(database_path)
            ),
            image_records=_opened(opened, SQLiteImageGenerationStore(database_path)),
            file_artifacts=file_artifacts,
            image_tasks=_opened(opened, SQLiteImageTaskStore(database_path)),
            tool_policy_store=_opened(opened, SQLiteToolPolicyStore(database_path)),
            workspace_directories=workspace_directories,
            data_analysis_register=data_analysis_register,
            agent_state_register=agent_state_register,
            agent_trace_register=agent_trace_register,
            agent_run_executor=agent_run_executor,
            tool_execution_register=tool_execution_register,
            runtime_data_tools_enabled=runtime_data_tools_enabled,
            sandbox=sandbox,
            context=context,
            prompt_cache_mode=prompt_cache_mode,
            prompt_cache_scope=prompt_cache_scope,
        )
        recovery = DeferredAgentRunRecovery(runtime)
        return runtime
    except BaseException:
        close_opened_resources(opened)
        raise


def runtime_state_paths(database_path: str | Path) -> list[Path]:
    """Files holding runtime state or secrets that tools must never touch."""
    database = Path(database_path).resolve()
    return [
        database,
        Path(str(database) + ".provider-key"),
        Path.cwd() / ".evernight",
        Path.cwd() / "config.toml",
        Path.cwd() / ".env",
    ]


def close_opened_resources(resources: list[Any]) -> None:
    """Closes resources from a failed assembly; the original error wins."""
    for resource in reversed(resources):
        close = getattr(resource, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception:
            LOGGER.exception("Failed to close %s", type(resource).__name__)


def _opened[T](opened: list[Any], resource: T) -> T:
    opened.append(resource)
    return resource


def _create_runtime(
    *,
    startup_handlers: list[Callable[[], Awaitable[None]]] | None = None,
    shutdown_handlers: list[Callable[[], Awaitable[None]]] | None = None,
    memory_strategy: MemoryStrategyProtocol | None = None,
    memory_write_strategy: MemoryWriteStrategyProtocol | None = None,
    tool_register: ToolRegisterProtocol | None = None,
    tool_safety_policy: ToolSafetyPolicyProtocol | None = None,
    tool_policy_store: ToolPolicyStoreProtocol | None = None,
    workspace_directories: WorkspaceDirectoryProtocol | None = None,
    tool_sources: list[ToolSourceProtocol] | None = None,
    context_register: ContextRegisterProtocol,
    memory_register: MemoryRegisterProtocol,
    session_register: SessionRegisterProtocol,
    provider_config_store: ProviderConfigStoreProtocol | None = None,
    provider_secret_resolver: ProviderSecretResolverProtocol | None = None,
    skill_template_store: SkillTemplateStoreProtocol | None = None,
    image_records: ImageGenerationStoreProtocol | None = None,
    file_artifacts: FileArtifactStoreProtocol | None = None,
    image_tasks: ImageTaskStoreProtocol | None = None,
    data_analysis_register: DataAnalysisRegisterProtocol | None = None,
    data_analysis: DataAnalysisManageProtocol | None = None,
    sessions: SessionManageProtocol | None = None,
    skill_register: SkillRegisterProtocol | None = None,
    skills: SkillManageProtocol | None = None,
    agent_state_register: AgentRunStateRegisterProtocol | None = None,
    agent_trace_register: AgentTraceRegisterProtocol | None = None,
    agent_run_executor: AgentRunExecutorProtocol | None = None,
    tool_execution_register: ToolExecutionRegisterProtocol | None = None,
    runtime_data_tools_enabled: bool = False,
    sandbox: SandboxExecuteProtocol | None = None,
    context: ContextStrategyOptions = ContextStrategyOptions(),
    prompt_cache_mode: PromptCacheMode = PromptCacheMode.PREFER_EXPLICIT,
    prompt_cache_scope: PromptCacheScope = PromptCacheScope.CONTEXT,
) -> RuntimeKernel:
    provider_factory = create_provider_factory()
    providers = ProviderManager(
        provider_factory,
        config_store=provider_config_store,
        secret_resolver=provider_secret_resolver or EnvironmentProviderSecretResolver(),
    )
    tool_register = tool_register or ToolRegister()
    tool_safety_policy = tool_safety_policy or BasicToolSafetyPolicy()
    sandbox = sandbox or SubprocessSandboxExecutor()
    tools = ToolManager(tool_register, tool_safety_policy, tool_policy_store)
    skill_register = skill_register or SkillRegister()
    register_echo_skill(skill_register)
    skills = skills or create_skill_manager(skill_register, skill_template_store)
    contexts = ContextManager(context_register)
    context_organizer = ContextOrganizer()
    context_strategy = create_context_strategy(context_organizer, context)
    data_analysis_register = data_analysis_register or DataAnalysisRegister()
    data_analysis = data_analysis or DataAnalysisManager(data_analysis_register)
    memories = MemoryManager(memory_register)
    if memory_strategy is None:
        memory_strategy = BasicMemoryStrategy()
    if memory_write_strategy is None:
        memory_write_strategy = BasicMemoryWriteStrategy()
    sessions = sessions or SessionManager(session_register)
    if runtime_data_tools_enabled:
        register_runtime_data_tools(
            tool_register,
            contexts=contexts,
            memories=memories,
            sessions=sessions,
        )

    async def execute_image_task(task: ImageTask) -> ImageTask:
        return await ImageTaskApplication(runtime).execute(task)

    image_tasks = image_tasks or ImageTaskStore()
    executor = SingleProcessImageTaskExecutor(image_tasks, execute_image_task)
    runtime = RuntimeKernel(
        startup_handlers=startup_handlers,
        shutdown_handlers=shutdown_handlers,
        provider_factory=provider_factory,
        providers=providers,
        provider_config_store=provider_config_store,
        image_records=image_records,
        file_artifacts=file_artifacts,
        image_archive=PublicImageArchive(),
        image_tasks=image_tasks,
        image_task_executor=executor,
        tool_register=tool_register,
        tools=tools,
        tool_safety_policy=tool_safety_policy,
        tool_policy_store=tool_policy_store,
        workspace_directories=workspace_directories,
        tool_sources=tool_sources,
        sandbox=sandbox,
        skill_register=skill_register,
        skills=skills,
        context_register=context_register,
        contexts=contexts,
        context_organizer=context_organizer,
        context_strategy=context_strategy,
        prompt_cache_mode=prompt_cache_mode,
        prompt_cache_scope=prompt_cache_scope,
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
        tool_execution_register=tool_execution_register,
    )
    if not tool_register.has("generate_image"):
        register_image_tool(tool_register, ImageToolApplication(runtime).execute)
    return runtime
