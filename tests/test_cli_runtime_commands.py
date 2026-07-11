from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.cli import main
from EvernightAI.core.domain.context import (
    BasicContextStrategy,
    ContextManager,
    ContextOrganizer,
    ContextRegister,
)
from EvernightAI.core.domain.memory import (
    BasicMemoryStrategy,
    BasicMemoryWriteStrategy,
    MemoryManager,
    MemoryRegister,
)
from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.core.domain.tool import BasicToolSafetyPolicy, ToolManager, ToolRegister
from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.infra.adapters.sandbox.bubblewrap import BubblewrapSandboxExecutor
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor
from EvernightAI.bootstrap.config import (
    create_sandbox_from_config,
    create_interface_from_config,
    create_runtime_from_config,
)
from EvernightAI.bootstrap.http import create_app_from_config
from EvernightAI.interface.cli.commands import list_models, list_providers, run_chat
from EvernightAI.interface.cli.config import parse_config
from tests.fakes.streams import EmptyStream


def test_list_providers_formats_declared_providers() -> None:
    config = parse_config(
        {
            "provider": {
                "main": {
                    "name": "DeepSeek",
                    "type": "openai",
                    "model": {"deepseek-chat": {"capabilities": ["chat"]}},
                },
                "off": {
                    "name": "Off",
                    "type": "anthropic",
                    "is_enabled": False,
                },
            }
        }
    )

    output = list_providers(config)

    assert "PROVIDER ID" in output
    assert "main" in output
    assert "DeepSeek" in output
    assert "openai" in output
    assert "anthropic" in output
    assert "no" in output


def test_list_providers_handles_empty_config() -> None:
    assert list_providers(parse_config({})) == "No providers declared."


def test_list_models_formats_declared_models() -> None:
    config = parse_config(
        {
            "provider": {
                "main": {
                    "name": "Main",
                    "type": "openai",
                    "model": {
                        "deepseek-chat": {"capabilities": ["chat", "tool_call"]},
                        "deepseek-reasoner": {"capabilities": ["chat"]},
                    },
                }
            }
        }
    )

    output = list_models(config, "main")

    assert "MODEL ID" in output
    assert "deepseek-chat" in output
    assert "chat, tool_call" in output
    assert "deepseek-reasoner" in output


def test_list_models_raises_for_unknown_provider() -> None:
    config = parse_config({})

    with pytest.raises(ConfigurationError):
        list_models(config, "missing")


def test_list_models_handles_provider_without_models() -> None:
    config = parse_config(
        {"provider": {"main": {"name": "Main", "type": "openai"}}}
    )

    assert list_models(config, "main") == "No models declared for provider 'main'."


@pytest.mark.asyncio
async def test_run_chat_creates_provider_and_returns_text() -> None:
    config = parse_config(
        {
            "provider": {
                "main": {"name": "Main", "type": "openai"},
            }
        }
    )
    interface = create_interface(make_runtime())

    try:
        output = await run_chat(
            interface,
            config,
            provider_id="main",
            model_id="deepseek-chat",
            prompt="hello",
        )
    finally:
        await interface.close()

    assert output == "ok"


@pytest.mark.asyncio
async def test_run_chat_raises_for_unknown_provider() -> None:
    interface = create_interface(make_runtime())

    try:
        with pytest.raises(ConfigurationError):
            await run_chat(
                interface,
                parse_config({}),
                provider_id="missing",
                model_id="x",
                prompt="hi",
            )
    finally:
        await interface.close()


@pytest.mark.asyncio
async def test_run_chat_rejects_disabled_provider() -> None:
    config = parse_config(
        {
            "provider": {
                "off": {
                    "name": "Off",
                    "type": "openai",
                    "is_enabled": False,
                }
            }
        }
    )
    interface = create_interface(make_runtime())

    try:
        with pytest.raises(ConfigurationError, match="disabled"):
            await run_chat(
                interface,
                config,
                provider_id="off",
                model_id="x",
                prompt="hi",
            )
    finally:
        await interface.close()


def test_cli_provider_list_prints_table(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[provider.main]
name = "Main"
type = "openai"
""".strip(),
        encoding="utf-8",
    )

    exit_code = main(["provider", "list", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "main" in captured.out
    assert "PROVIDER ID" in captured.out


def test_cli_model_list_prints_table(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[provider.main]
name = "Main"
type = "openai"

[provider.main.model.deepseek-chat]
capabilities = ["chat"]
""".strip(),
        encoding="utf-8",
    )

    exit_code = main(
        ["model", "list", "--provider", "main", "--config", str(config_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "deepseek-chat" in captured.out
    assert "MODEL ID" in captured.out


def test_cli_model_list_returns_error_for_unknown_provider(
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

    exit_code = main(
        ["model", "list", "--provider", "missing", "--config", str(config_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "ConfigurationError" in captured.err


def test_cli_chat_smoke_uses_configured_provider(
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
        lambda _config: create_interface(make_runtime()),
    )

    exit_code = main(
        [
            "chat",
            "--provider",
            "main",
            "--model",
            "deepseek-chat",
            "hello",
            "--config",
            str(config_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip() == "ok"


def test_cli_agent_run_approve_uses_pending_approvals(
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
    calls: list[str] = []

    class FakeInterface:
        async def close(self) -> None:
            pass

    async def approve(_interface: object, run_id: str) -> str:
        calls.append(run_id)
        return "approved"

    monkeypatch.setattr(
        "EvernightAI.entrypoint.cli.create_interface_from_config",
        lambda _config: FakeInterface(),
    )
    monkeypatch.setattr(
        "EvernightAI.entrypoint.cli.approve_pending_agent_run",
        approve,
    )

    exit_code = main(
        [
            "agent-run",
            "approve",
            "run-1",
            "--config",
            str(config_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip() == "approved"
    assert calls == ["run-1"]


def test_cli_chat_returns_error_for_unknown_provider(
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
        lambda _config: create_interface(make_runtime()),
    )

    exit_code = main(
        [
            "chat",
            "--provider",
            "missing",
            "--model",
            "x",
            "hello",
            "--config",
            str(config_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "ConfigurationError" in captured.err


def test_cli_chat_rejects_disabled_provider(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[provider.off]
name = "Off"
type = "openai"
is_enabled = false
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "EvernightAI.entrypoint.cli.create_interface_from_config",
        lambda _config: create_interface(make_runtime()),
    )

    exit_code = main(
        [
            "chat",
            "--provider",
            "off",
            "--model",
            "x",
            "hello",
            "--config",
            str(config_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "disabled" in captured.err


def test_create_runtime_from_config_registers_filesystem_tools_only(
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "tools": {
                "filesystem": {"enabled": True, "root": str(tmp_path)},
                "shell": {"enabled": False},
            },
        }
    )

    runtime = create_runtime_from_config(config)

    try:
        assert [tool.name for tool in runtime.tools.list_tools()] == [
            "read_text_file",
            "write_text_file",
            "append_text_file",
            "list_directory",
            "find_paths",
            "search_text_files",
            "read_text_file_lines",
            "move_path",
            "delete_path",
            "apply_text_patch",
            "file_hash",
            "path_info",
            "make_directory",
            "copy_path",
            "read_json_file",
            "write_json_file",
        ]
    finally:
        import asyncio

        asyncio.run(runtime.close())


def test_create_interface_from_config_wraps_configured_runtime(
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "tools": {
                "filesystem": {"enabled": True, "root": str(tmp_path)},
                "shell": {"enabled": False},
            },
        }
    )

    interface = create_interface_from_config(config)

    try:
        assert [tool.name for tool in interface.runtime.tools.list_tools()] == [
            "read_text_file",
            "write_text_file",
            "append_text_file",
            "list_directory",
            "find_paths",
            "search_text_files",
            "read_text_file_lines",
            "move_path",
            "delete_path",
            "apply_text_patch",
            "file_hash",
            "path_info",
            "make_directory",
            "copy_path",
            "read_json_file",
            "write_json_file",
        ]
    finally:
        import asyncio

        asyncio.run(interface.close())


def test_create_runtime_from_config_registers_shell_tool_when_enabled(
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "tools": {
                "filesystem": {"enabled": True, "root": str(tmp_path)},
                "shell": {
                    "enabled": True,
                    "allowed_commands": ["python"],
                    "working_directory": str(tmp_path),
                },
            },
        }
    )

    runtime = create_runtime_from_config(config)

    try:
        assert [tool.name for tool in runtime.tools.list_tools()] == [
            "read_text_file",
            "write_text_file",
            "append_text_file",
            "list_directory",
            "find_paths",
            "search_text_files",
            "read_text_file_lines",
            "move_path",
            "delete_path",
            "apply_text_patch",
            "file_hash",
            "path_info",
            "make_directory",
            "copy_path",
            "read_json_file",
            "write_json_file",
            "restricted_shell",
        ]
    finally:
        import asyncio

        asyncio.run(runtime.close())


def test_create_sandbox_from_config_uses_subprocess_by_default(
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
        }
    )

    assert isinstance(create_sandbox_from_config(config), SubprocessSandboxExecutor)


def test_create_sandbox_from_config_uses_bubblewrap_when_configured(
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "runtime": {
                "database_path": str(tmp_path / "runtime.sqlite3"),
                "sandbox_backend": "bubblewrap",
            },
        }
    )

    assert isinstance(create_sandbox_from_config(config), BubblewrapSandboxExecutor)


def test_create_app_from_config_serves_health_and_tools(
    tmp_path: Path,
) -> None:
    config = parse_config(
        {
            "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
            "http": {"host": "127.0.0.1", "port": 9001},
            "tools": {
                "filesystem": {"enabled": True, "root": str(tmp_path)},
                "shell": {"enabled": False},
            },
            "provider": {
                "main": {
                    "name": "Main",
                    "type": "openai",
                    "model": {
                        "chat": {
                            "model_id": "gpt-4.1-mini",
                            "capabilities": ["chat"],
                        }
                    },
                }
            },
        }
    )

    app = create_app_from_config(config, close_on_shutdown=False)

    with TestClient(app) as client:
        health_response = client.get("/health")
        tools_response = client.get("/tools")
        models_response = client.get("/providers/main/models")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert [tool["name"] for tool in tools_response.json()] == [
        "read_text_file",
        "write_text_file",
        "append_text_file",
        "list_directory",
        "find_paths",
        "search_text_files",
        "read_text_file_lines",
        "move_path",
        "delete_path",
        "apply_text_patch",
        "file_hash",
        "path_info",
        "make_directory",
        "copy_path",
        "read_json_file",
        "write_json_file",
    ]
    assert models_response.status_code == 200
    assert [model["model_id"] for model in models_response.json()] == [
        "gpt-4.1-mini"
    ]


def make_runtime() -> RuntimeKernel:
    async def build_provider(_config: ProviderConfig) -> ProviderInstanceProtocol:
        return FakeProvider()

    provider_factory = ProviderFactory()
    provider_factory.register(ProviderType.OPENAI, build_provider)
    provider_factory.register(ProviderType.OPENAI_RESPONSES, build_provider)
    provider_factory.register(ProviderType.GOOGLE, build_provider)
    provider_factory.register(ProviderType.ANTHROPIC, build_provider)
    tool_register = ToolRegister()
    tool_safety_policy = BasicToolSafetyPolicy()
    context_register = ContextRegister()
    context_organizer = ContextOrganizer()
    memory_register = MemoryRegister()

    return RuntimeKernel(
        provider_factory=provider_factory,
        providers=ProviderManager(provider_factory),
        tool_register=tool_register,
        tools=ToolManager(tool_register, tool_safety_policy),
        tool_safety_policy=tool_safety_policy,
        context_register=context_register,
        contexts=ContextManager(context_register),
        context_organizer=context_organizer,
        context_strategy=BasicContextStrategy(context_organizer),
        memory_register=memory_register,
        memories=MemoryManager(memory_register),
        memory_strategy=BasicMemoryStrategy(),
        memory_write_strategy=BasicMemoryWriteStrategy(),
    )


class FakeProvider(ProviderInstanceProtocol):
    def __init__(self) -> None:
        self.last_request: ChatRequest | None = None

    async def list_models(self) -> list[ProviderModelConfig]:
        return [
            ProviderModelConfig(
                model_id="deepseek-chat",
                capabilities=[ProviderModelCapability.CHAT],
            )
        ]

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return ProviderModelConfig(model_id=model_id)

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return capability is ProviderModelCapability.CHAT

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_request = request
        return ChatResponse(
            model_id=request.model_id,
            message=Content(
                role=MessageRole.ASSISTANT,
                content=[ContentPart(type=ContentPartType.TEXT, text="ok")],
            ),
            finish_reason="stop",
        )

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        self.last_request = request
        return EmptyStream()

    async def close(self) -> None:
        pass
