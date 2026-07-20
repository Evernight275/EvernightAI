from pathlib import Path

import pytest

from EvernightAI.core.schema.provider import (
    ProviderModelCapability,
    ProviderType,
)
from EvernightAI.core.schema.content import PromptCacheMode, PromptCacheScope
from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.interface.cli.schema import McpTransport, SandboxBackend
from EvernightAI.interface.cli.config import load_config, parse_config


def test_parse_config_maps_toml_shape_to_core_provider_config(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")
    monkeypatch.setenv("OAUTH_ACCESS_TOKEN", "oauth-token")

    config = parse_config(
        {
            "runtime": {
                "database_path": ".evernight/test.sqlite3",
                "sandbox_backend": "bubblewrap",
            },
            "prompt_cache": {
                "mode": "prefer_explicit",
                "scope": "owner",
            },
            "http": {
                "host": "0.0.0.0",
                "port": 8080,
                "reload": True,
                "server_header": "EvernightAdmin",
                "static_files_path": "frontend/dist",
            },
            "tools": {
                "filesystem": {
                    "enabled": True,
                    "root": ".",
                    "max_read_chars": 8000,
                    "max_search_results": 25,
                    "allow_write": True,
                },
                "shell": {
                    "enabled": True,
                    "allowed_commands": ["python", "pytest"],
                    "blocked_commands": ["python -c"],
                    "timeout_seconds": 3.5,
                    "is_need_approval": False,
                    "allowed_env_keys": ["PYTHONPATH"],
                },
                "web": {
                    "enabled": True,
                    "allowed_hosts": ["example.test"],
                    "download_directory": "downloads",
                    "max_response_chars": 4000,
                },
                "git": {
                    "enabled": True,
                    "repository_directory": ".",
                },
                "project": {
                    "enabled": True,
                    "working_directory": ".",
                    "commands": {"tests": ["python", "-m", "pytest"]},
                    "project_directories": {
                        "EvernightAI": "/home/cyrene/EvernightAI"
                    },
                    "projects": {
                        "EvernightAI": {
                            "tests": ["uv", "run", "pytest"],
                        }
                    },
                },
                "runtime_data": {
                    "enabled": True,
                },
                "mcp": {
                    "server": {
                        "github": {
                            "url": "https://mcp.example.test/mcp",
                            "namespace": "gh",
                            "token_env": "GITHUB_MCP_TOKEN",
                            "allowed_tools": ["search", "get_file"],
                            "blocked_tools": ["delete_repository"],
                            "max_tools": 25,
                            "max_definition_chars": 4000,
                            "watch_tool_changes": True,
                            "refresh_interval_seconds": 60,
                            "timeout_seconds": 15,
                            "max_output_chars": 6000,
                            "is_need_approval": False,
                        }
                    }
                },
            },
            "auth": {
                "enabled": True,
                "principal": {
                    "admin": {
                        "api_key_env": "DEEPSEEK_API_KEY",
                        "roles": ["admin"],
                        "permissions": ["*"],
                    }
                },
                "oauth": {
                    "jwt": {
                        "issuer": "https://idp.example.test",
                        "audience": ["evernight-admin-api"],
                        "jwks_url": "https://idp.example.test/.well-known/jwks.json",
                        "algorithms": ["RS256"],
                        "roles_claim": "realm_access.roles",
                        "role_permission_map": {"evernight-admin": ["*"]},
                        "scope_permission_map": {"evernight.tools": ["tools:list"]},
                    },
                    "token": {
                        "reader": {
                            "access_token_env": "OAUTH_ACCESS_TOKEN",
                            "roles": ["reader"],
                            "permissions": ["tools:list"],
                        }
                    }
                },
            },
            "data_analysis": {
                "sqlite_source": {
                    "orders": {
                        "name": "Orders",
                        "table": "orders_view",
                        "field": {
                            "status": {
                                "field_type": "string",
                            },
                            "amount": {
                                "field_type": "number",
                            },
                        },
                        "metric": {
                            "order_count": {
                                "aggregation": "count",
                            },
                            "revenue": {
                                "aggregation": "sum",
                                "field_id": "amount",
                            },
                        },
                    }
                }
            },
            "provider": {
                "main": {
                    "name": "DeepSeek",
                    "type": "openai",
                    "discover_models": True,
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "base_url": "https://example.test/v1",
                    "metadata": {"source": "test"},
                    "model": {
                        "deepseek-chat": {
                            "capabilities": ["chat", "tool_call"],
                        }
                    },
                }
            },
        }
    )

    provider = config.providers[0]
    model = provider.model["deepseek-chat"]

    assert config.runtime.database_path == ".evernight/test.sqlite3"
    assert config.runtime.sandbox_backend is SandboxBackend.BUBBLEWRAP
    assert config.prompt_cache.mode is PromptCacheMode.PREFER_EXPLICIT
    assert config.prompt_cache.scope is PromptCacheScope.OWNER
    assert config.http.host == "0.0.0.0"
    assert config.http.port == 8080
    assert config.http.reload is True
    assert config.http.server_header == "EvernightAdmin"
    assert config.http.static_files_path == "frontend/dist"
    assert config.tools.filesystem.enabled is True
    assert config.tools.filesystem.root == "."
    assert config.tools.filesystem.max_read_chars == 8000
    assert config.tools.filesystem.max_search_results == 25
    assert config.tools.filesystem.allow_write is True
    assert config.tools.shell.enabled is True
    assert config.tools.shell.allowed_commands == ["python", "pytest"]
    assert config.tools.shell.blocked_commands == ["python -c"]
    assert config.tools.shell.timeout_seconds == 3.5
    assert config.tools.shell.is_need_approval is False
    assert config.tools.shell.allowed_env_keys == ["PYTHONPATH"]
    assert config.tools.web.enabled is True
    assert config.tools.web.allowed_hosts == ["example.test"]
    assert config.tools.web.download_directory == "downloads"
    assert config.tools.web.max_response_chars == 4000
    assert config.tools.git.enabled is True
    assert config.tools.git.repository_directory == "."
    assert config.tools.project.enabled is True
    assert config.tools.project.commands == {"tests": ["python", "-m", "pytest"]}
    assert config.tools.project.project_directories == {
        "EvernightAI": "/home/cyrene/EvernightAI"
    }
    assert config.tools.project.projects == {
        "EvernightAI": {"tests": ["uv", "run", "pytest"]}
    }
    assert config.tools.runtime_data.enabled is True
    mcp_server = config.tools.mcp.server["github"]
    assert mcp_server.url == "https://mcp.example.test/mcp"
    assert mcp_server.transport is McpTransport.STREAMABLE_HTTP
    assert mcp_server.namespace == "gh"
    assert mcp_server.token_env == "GITHUB_MCP_TOKEN"
    assert mcp_server.allowed_tools == ["search", "get_file"]
    assert mcp_server.blocked_tools == ["delete_repository"]
    assert mcp_server.max_tools == 25
    assert mcp_server.max_definition_chars == 4000
    assert mcp_server.watch_tool_changes is True
    assert mcp_server.refresh_interval_seconds == 60
    assert mcp_server.timeout_seconds == 15
    assert mcp_server.max_output_chars == 6000
    assert mcp_server.is_need_approval is False
    assert config.data_analysis.sqlite_sources[0].source_id == "orders"
    assert config.data_analysis.sqlite_sources[0].name == "Orders"
    assert config.data_analysis.sqlite_sources[0].table == "orders_view"
    assert config.data_analysis.sqlite_sources[0].fields[0].field_id == "status"
    assert config.data_analysis.sqlite_sources[0].fields[0].field_type == "string"
    assert config.data_analysis.sqlite_sources[0].metrics[0].metric_id == "order_count"
    assert config.data_analysis.sqlite_sources[0].metrics[0].aggregation == "count"
    assert config.auth.enabled is True
    assert config.auth.principals[0].principal_id == "admin"
    assert config.auth.principals[0].api_key == "secret-key"
    assert config.auth.principals[0].roles == ["admin"]
    assert config.auth.principals[0].permissions == ["*"]
    assert config.auth.oauth.tokens[0].principal_id == "reader"
    assert config.auth.oauth.tokens[0].access_token == "oauth-token"
    assert config.auth.oauth.tokens[0].roles == ["reader"]
    assert config.auth.oauth.tokens[0].permissions == ["tools:list"]
    assert config.auth.oauth.jwt is not None
    assert config.auth.oauth.jwt.issuer == "https://idp.example.test"
    assert config.auth.oauth.jwt.audience == ["evernight-admin-api"]
    assert (
        config.auth.oauth.jwt.jwks_url
        == "https://idp.example.test/.well-known/jwks.json"
    )
    assert config.auth.oauth.jwt.roles_claim == "realm_access.roles"
    assert config.auth.oauth.jwt.role_permission_map == {"evernight-admin": ["*"]}
    assert config.auth.oauth.jwt.scope_permission_map == {
        "evernight.tools": ["tools:list"]
    }
    assert provider.provider_id == "main"
    assert provider.name == "DeepSeek"
    assert provider.type is ProviderType.OPENAI
    assert provider.discover_models is True
    assert provider.api_key == "secret-key"
    assert provider.base_url == "https://example.test/v1"
    assert provider.metadata == {"source": "test"}
    assert model.model_id == "deepseek-chat"
    assert model.capabilities == [
        ProviderModelCapability.CHAT,
        ProviderModelCapability.TOOL_CALL,
    ]


def test_load_config_reads_toml_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[runtime]
database_path = ".evernight/runtime.sqlite3"

[provider.main]
name = "Local"
type = "openai"
api_key = "inline-key"

[provider.main.model.model_1]
model_id = "model-1"
capabilities = ["chat"]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.runtime.database_path == ".evernight/runtime.sqlite3"
    assert config.prompt_cache.mode is PromptCacheMode.PREFER_EXPLICIT
    assert config.prompt_cache.scope is PromptCacheScope.CONTEXT
    assert config.runtime.sandbox_backend is SandboxBackend.SUBPROCESS
    assert config.providers[0].provider_id == "main"
    assert config.providers[0].api_key == "inline-key"
    assert list(config.providers[0].model) == ["model-1"]


def test_parse_config_uses_defaults_for_missing_sections() -> None:
    config = parse_config({})

    assert config.runtime.database_path == ".evernight/runtime.sqlite3"
    assert config.http.host == "127.0.0.1"
    assert config.http.port == 8000
    assert config.http.server_header == "EvernightAI"
    assert config.tools.filesystem.enabled is False
    assert config.tools.web.enabled is False
    assert config.tools.git.enabled is False
    assert config.tools.project.enabled is False
    assert config.tools.runtime_data.enabled is False
    assert config.tools.mcp.server == {}
    assert config.tools.shell.allowed_commands == []
    assert config.tools.shell.blocked_commands == []
    assert config.auth.enabled is False
    assert config.auth.principals == []
    assert config.data_analysis.sqlite_sources == []
    assert config.providers == []


def test_parse_config_rejects_unknown_provider_model_fields() -> None:
    try:
        parse_config(
            {
                "provider": {
                    "main": {
                        "type": "openai",
                        "model": {
                            "chat": {
                                "del_id": "gpt-test",
                                "capabilities": ["chat"],
                            }
                        },
                    }
                }
            }
        )
    except ConfigurationError as exc:
        assert "del_id" in str(exc.detail)
    else:
        raise AssertionError("Expected ConfigurationError")


def test_parse_config_validates_mcp_transport_specific_fields() -> None:
    config = parse_config(
        {
            "tools": {
                "mcp": {
                    "server": {
                        "local": {
                            "transport": "stdio",
                            "command": "python",
                            "args": ["server.py"],
                            "cwd": ".",
                            "env_from": {"API_TOKEN": "MCP_API_TOKEN"},
                        },
                        "legacy": {
                            "transport": "sse",
                            "url": "https://mcp.example.test/sse",
                        },
                    }
                }
            }
        }
    )

    assert config.tools.mcp.server["local"].transport is McpTransport.STDIO
    assert config.tools.mcp.server["local"].command == "python"
    assert config.tools.mcp.server["legacy"].transport is McpTransport.SSE

    with pytest.raises(ConfigurationError, match="Invalid EvernightAI config"):
        parse_config(
            {
                "tools": {
                    "mcp": {
                        "server": {
                            "invalid": {
                                "transport": "stdio",
                                "url": "https://mcp.example.test/mcp",
                            }
                        }
                    }
                }
            }
        )
