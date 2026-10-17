from typing import Any, cast
import sqlite3

import pytest

from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.application.agent import AgentApplication, AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.application.provider import ProviderApplication
from EvernightAI.application.session import SessionApplication
from EvernightAI.bootstrap.config import (
    create_interface_from_config,
    create_runtime_from_config,
)
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.runtime import create_runtime, create_sqlite_runtime
from EvernightAI.core.error.auth import AuthRequiredError
from EvernightAI.infra.adapters.tool.file_artifacts import SQLiteFileArtifactStore
from EvernightAI.infra.adapters.tool.workspace_directory import WorkspaceDirectoryStore
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.interface import EvernightInterface
from EvernightAI.core.error.tool import ToolConfigurationError
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
    PromptCacheScope,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.data_analysis import (
    DataSort,
    DataSortDirection,
    DataStatisticsRequest,
)
from EvernightAI.interface.cli.config import parse_config


def test_interface_bootstrap_wraps_existing_runtime() -> None:
    runtime = create_runtime()

    interface: EvernightInterfaceProtocol = create_interface(runtime)

    assert isinstance(interface, EvernightInterface)
    assert interface.runtime is runtime
    assert isinstance(interface.chat, ChatApplication)
    assert isinstance(interface.providers, ProviderApplication)
    assert interface.tools is runtime.tools
    assert interface.data_analysis is runtime.data_analysis
    assert isinstance(interface.agent, AgentApplication)
    assert isinstance(interface.agent_runs, AgentRunApplication)
    assert interface.skills is runtime.skills
    assert isinstance(interface.sessions, SessionApplication)


def test_authorized_interface_wraps_existing_interface() -> None:
    interface = create_interface(create_runtime())

    authorized: EvernightInterfaceProtocol = AuthorizedEvernightInterface(
        interface,
        Authorizer(PermissionAuthPolicy()),
        Principal(principal_id="user-1", permissions=["*"]),
    )

    assert isinstance(authorized, AuthorizedEvernightInterface)
    assert authorized.runtime is interface.runtime


@pytest.mark.asyncio
async def test_authorized_interface_lifecycle_delegates_to_runtime() -> None:
    runtime = create_runtime()
    authorized = AuthorizedEvernightInterface(
        create_interface(runtime),
        Authorizer(PermissionAuthPolicy()),
        Principal(principal_id="user-1", permissions=["*"]),
    )

    await authorized.initialize()

    assert runtime.is_ready is True

    await authorized.close()


def test_configured_context_strategy_composes_runtime_window(tmp_path) -> None:
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "context_strategy": {
                "max_messages": 2,
                "max_tokens": 1000,
            },
        }
    )
    runtime = create_runtime_from_config(config)

    request = runtime.context_strategy.compose_chat_request(
        Context(
            context_id="ctx-1",
            messages=[
                _message("one"),
                _message("two"),
            ],
        ),
        model_id="model-1",
        messages=[_message("three")],
    )

    assert [
        message.content[0].text for message in request.messages if message.content
    ] == [
        "two",
        "three",
    ]
    assert [step["name"] for step in request.metadata["context_strategy_steps"]] == [
        "WindowTrimmingContextStrategy",
        "TokenBudgetContextStrategy",
    ]


@pytest.mark.asyncio
async def test_configured_prompt_cache_scope_reaches_chat_composer(tmp_path) -> None:
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "prompt_cache": {"scope": "owner"},
        }
    )
    runtime = create_runtime_from_config(config)
    app = ChatApplication(runtime)
    await app.create_context(Context(context_id="ctx-1", owner_id="user-1"))
    await app.create_context(Context(context_id="ctx-2", owner_id="user-1"))

    first = await app.organize_chat_request("ctx-1", model_id="model-1")
    second = await app.organize_chat_request("ctx-2", model_id="model-1")

    assert runtime.prompt_cache_scope is PromptCacheScope.OWNER
    assert first.prompt_cache is not None
    assert second.prompt_cache is not None
    assert first.prompt_cache.scope is PromptCacheScope.OWNER
    assert first.prompt_cache.scope_id == second.prompt_cache.scope_id


def test_configured_shell_can_disable_tool_approval(tmp_path) -> None:
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "tools": {
                "shell": {
                    "enabled": True,
                    "allowed_commands": ["uv"],
                    "blocked_commands": ["uv publish"],
                    "is_need_approval": False,
                }
            },
        }
    )

    runtime = create_runtime_from_config(config)

    definition = runtime.tool_register.get("restricted_shell")

    assert definition.requires_approval is False
    assert definition.metadata["blocked_commands"] == ["uv publish"]


def test_configured_mcp_server_creates_runtime_tool_source(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_TOKEN", "secret")
    monkeypatch.setenv("MCP_STDIO_TOKEN", "stdio-secret")
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "tools": {
                "mcp": {
                    "server": {
                        "github": {
                            "url": "https://mcp.example.test/mcp",
                            "namespace": "gh",
                            "token_env": "MCP_TOKEN",
                        },
                        "disabled": {
                            "enabled": False,
                            "url": "https://disabled.example.test/mcp",
                        },
                        "local": {
                            "transport": "stdio",
                            "command": "python",
                            "args": ["server.py"],
                            "env_from": {"API_TOKEN": "MCP_STDIO_TOKEN"},
                        },
                    }
                }
            },
        }
    )

    runtime = create_runtime_from_config(config)

    assert len(runtime.tool_sources) == 2


def test_configured_mcp_server_requires_declared_token_environment(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_MCP_TOKEN", raising=False)
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "tools": {
                "mcp": {
                    "server": {
                        "github": {
                            "url": "https://mcp.example.test/mcp",
                            "token_env": "MISSING_MCP_TOKEN",
                        }
                    }
                }
            },
        }
    )

    with pytest.raises(ToolConfigurationError, match="MISSING_MCP_TOKEN"):
        create_runtime_from_config(config)


def test_configured_project_directories_register_with_runtime(tmp_path) -> None:
    project_directory = tmp_path / "other-project"
    project_directory.mkdir()
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "tools": {
                "filesystem": {
                    "enabled": True,
                    "root": str(tmp_path),
                },
                "project": {
                    "enabled": True,
                    "working_directory": str(tmp_path),
                    "commands": {"inspect": ["python", "--version"]},
                    "project_directories": {"OtherProject": str(project_directory)},
                },
            },
        }
    )

    runtime = create_runtime_from_config(config)
    definition = runtime.tool_register.get("run_project_task")
    read_definition = runtime.tool_register.get("read_text_file")
    write_definition = runtime.tool_register.get("write_text_file")

    assert definition.metadata["project_directories"] == ["OtherProject"]
    assert read_definition.metadata["projects"] == ["OtherProject"]
    assert read_definition.parameters_schema is not None
    assert read_definition.parameters_schema["properties"]["project"] == {
        "type": "string",
        "enum": ["OtherProject"],
    }
    assert write_definition.parameters_schema is not None
    assert write_definition.parameters_schema["properties"]["project"] == {
        "type": "string",
        "enum": ["OtherProject"],
    }


def test_project_directories_are_shared_without_project_task_tool(tmp_path) -> None:
    project_directory = tmp_path / "other-project"
    project_directory.mkdir()
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "tools": {
                "filesystem": {"enabled": True, "root": str(tmp_path)},
                "git": {"enabled": True, "repository_directory": str(tmp_path)},
                "project": {
                    "enabled": False,
                    "project_directories": {"OtherProject": str(project_directory)},
                },
            },
        }
    )

    runtime = create_runtime_from_config(config)
    read_definition = runtime.tool_register.get("read_text_file")
    git_definition = runtime.tool_register.get("git_status")

    assert read_definition.metadata["projects"] == ["OtherProject"]
    assert git_definition.metadata["projects"] == ["OtherProject"]
    assert git_definition.parameters_schema is not None
    assert git_definition.parameters_schema["properties"]["project"] == {
        "type": "string",
        "enum": ["OtherProject"],
    }


def test_configured_context_summary_requires_summarizer(tmp_path) -> None:
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "context_strategy": {"enable_summary": True},
        }
    )

    with pytest.raises(ConfigurationError, match="enable_summary"):
        create_runtime_from_config(config)

    assert not (tmp_path / "runtime.sqlite3").exists()


def _message(text: str) -> Content:
    return Content(
        role=MessageRole.USER,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


@pytest.mark.asyncio
async def test_runtime_close_closes_registered_stores() -> None:
    runtime = create_runtime()
    closed: list[str] = []

    cast(Any, runtime.context_register).close = lambda: closed.append("context")
    cast(Any, runtime.data_analysis_register).close = lambda: closed.append(
        "data_analysis"
    )
    cast(Any, runtime.memory_register).close = lambda: closed.append("memory")
    cast(Any, runtime.session_register).close = lambda: closed.append("session")

    await runtime.close()

    assert closed == ["context", "data_analysis", "memory", "session"]


@pytest.mark.asyncio
async def test_interface_close_drains_agent_runs_before_runtime_close() -> None:
    runtime = create_runtime()
    interface = create_interface(runtime)
    closed: list[str] = []

    async def close_agent_runs() -> None:
        closed.append("agent_runs")

    async def close_runtime() -> None:
        closed.append("runtime")

    cast(Any, interface.agent_runs).close = close_agent_runs
    cast(Any, interface.runtime).close = close_runtime

    await interface.close()

    assert closed == ["agent_runs", "runtime"]


@pytest.mark.asyncio
async def test_runtime_close_continues_after_a_store_fails_to_close() -> None:
    runtime = create_runtime()
    closed: list[str] = []

    def fail_context_close() -> None:
        raise RuntimeError("context close failed")

    cast(Any, runtime.context_register).close = fail_context_close
    cast(Any, runtime.session_register).close = lambda: closed.append("session")

    with pytest.raises(RuntimeError, match="context close failed"):
        await runtime.close()

    assert closed == ["session"]


@pytest.mark.asyncio
async def test_interface_close_closes_runtime_when_agent_drain_fails() -> None:
    runtime = create_runtime()
    interface = create_interface(runtime)
    closed: list[str] = []

    async def fail_agent_runs_close() -> None:
        raise RuntimeError("drain failed")

    async def close_runtime() -> None:
        closed.append("runtime")

    cast(Any, interface.agent_runs).close = fail_agent_runs_close
    cast(Any, interface.runtime).close = close_runtime

    with pytest.raises(RuntimeError, match="drain failed"):
        await interface.close()

    assert closed == ["runtime"]


def test_sqlite_runtime_closes_opened_stores_when_assembly_fails(
    tmp_path,
    monkeypatch,
) -> None:
    closed: list[str] = []

    class RecordingFileArtifactStore(SQLiteFileArtifactStore):
        def close(self) -> None:
            closed.append("file_artifacts")
            super().close()

    def fail_recovery(*args: object, **kwargs: object) -> int:
        raise RuntimeError("recovery failed")

    monkeypatch.setattr(
        "EvernightAI.bootstrap.runtime.SQLiteFileArtifactStore",
        RecordingFileArtifactStore,
    )
    monkeypatch.setattr(
        "EvernightAI.bootstrap.runtime.register_sqlite_runtime_data_analysis_sources",
        fail_recovery,
    )

    with pytest.raises(RuntimeError, match="recovery failed"):
        create_sqlite_runtime(tmp_path / "runtime.sqlite3")

    assert closed == ["file_artifacts"]


def test_configured_runtime_closes_workspaces_when_assembly_fails(
    tmp_path,
    monkeypatch,
) -> None:
    closed: list[str] = []

    class RecordingWorkspaceDirectoryStore(WorkspaceDirectoryStore):
        def close(self) -> None:
            closed.append("workspaces")
            super().close()

    def fail_runtime(*args: object, **kwargs: object) -> None:
        raise RuntimeError("runtime assembly failed")

    monkeypatch.setattr(
        "EvernightAI.bootstrap.config.WorkspaceDirectoryStore",
        RecordingWorkspaceDirectoryStore,
    )
    monkeypatch.setattr(
        "EvernightAI.bootstrap.config.create_sqlite_runtime",
        fail_runtime,
    )
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "tools": {"filesystem": {"enabled": True, "root": str(tmp_path)}},
        }
    )

    with pytest.raises(RuntimeError, match="runtime assembly failed"):
        create_runtime_from_config(config)

    assert closed == ["workspaces"]


def test_cli_interface_checks_credentials_before_creating_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    for name in (
        "EVERNIGHTAI_CLI_API_KEY",
        "EVERNIGHTAI_CLI_USERNAME",
        "EVERNIGHTAI_CLI_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    database_path = tmp_path / "runtime.sqlite3"
    config = parse_config(
        {
            "runtime": {"database_path": str(database_path)},
            "auth": {
                "enabled": True,
                "users": [{"username": "admin", "password": "secret"}],
            },
        }
    )

    with pytest.raises(AuthRequiredError):
        create_interface_from_config(config)

    assert not database_path.exists()


@pytest.mark.asyncio
async def test_configured_sqlite_data_sources_register_with_runtime(tmp_path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute(
        "CREATE TABLE orders (status TEXT NOT NULL, amount REAL NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO orders (status, amount) VALUES (?, ?)",
        [("paid", 30), ("paid", 12), ("refunded", 5)],
    )
    connection.commit()
    connection.close()
    config = parse_config(
        {
            "runtime": {"database_path": str(database_path)},
            "data_analysis": {
                "sqlite_source": {
                    "orders": {
                        "name": "Orders",
                        "table": "orders",
                        "field": {
                            "status": {"field_type": "string"},
                            "amount": {"field_type": "number"},
                        },
                        "metric": {
                            "order_count": {"aggregation": "count"},
                            "revenue": {
                                "aggregation": "sum",
                                "field_id": "amount",
                            },
                        },
                    }
                }
            },
        }
    )
    runtime = create_runtime_from_config(config)

    result = await runtime.data_analysis.statistics(
        DataStatisticsRequest(
            source_id="orders",
            metrics=["order_count", "revenue"],
            dimensions=["status"],
            sorts=[DataSort(field_id="revenue", direction=DataSortDirection.DESC)],
        )
    )

    await runtime.close()
    assert [source.source_id for source in runtime.data_analysis.list_sources()] == [
        "agent_runs",
        "agent_trace_events",
        "sessions",
        "contexts",
        "memories",
        "orders",
    ]
    assert result.rows[0].dimensions == {"status": "paid"}
    assert result.rows[0].metrics == {"order_count": 2, "revenue": 42.0}
