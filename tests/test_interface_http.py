import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import jwt
from fastapi.testclient import TestClient

from EvernightAI.core.domain.context import (
    BasicContextStrategy,
    ContextManager,
    ContextOrganizer,
    ContextRegister,
)
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.memory import (
    BasicMemoryStrategy,
    BasicMemoryWriteStrategy,
    MemoryManager,
    MemoryRegister,
)
from EvernightAI.core.domain.provider import ProviderFactory, ProviderManager
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.core.domain.tool import BasicToolSafetyPolicy, ToolManager, ToolRegister
from EvernightAI.core.error.agent import AgentStateError
from EvernightAI.core.error.auth import AuthPermissionDeniedError, AuthRequiredError
from EvernightAI.core.error.provider import ProviderUnavailableError
from EvernightAI.core.protocol.agent import (
    AgentRunStateRegisterProtocol,
    AgentTraceRegisterProtocol,
)
from EvernightAI.core.protocol.provider import ProviderInstanceProtocol
from EvernightAI.core.protocol.stream import ChatStreamProtocol
from EvernightAI.core.schema.agent import AgentRunState, AgentTraceEvent
from EvernightAI.core.schema.auth import Principal
from EvernightAI.core.schema.content import (
    ChatRequest,
    ChatResponse,
    Content,
    ContentPart,
    ContentPartType,
    MessageStatus,
    MessageRole,
)
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.data_analysis import (
    DataAggregation,
    DataAnalysisRequest,
    DataAnalysisResult,
    DataFieldDefinition,
    DataFieldType,
    DataInsight,
    DataInsightKind,
    DataMetricDefinition,
    DataSourceDefinition,
    DataStatisticsRequest,
    DataStatisticsResult,
    DataStatisticsRow,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelCapability,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.skill import (
    RenderedSkill,
    SkillCapability,
    SkillDefinition,
    SkillRenderRequest,
)
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)
from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.interface.http.app import create_http_app
from EvernightAI.interface.http.auth import (
    ApiKeyHttpAuthDevice,
    OAuthBearerHttpAuthDevice,
    OAuthJwtBearerHttpAuthDevice,
)
from EvernightAI.interface.http.schema import (
    HttpApiKeyCredential,
    HttpOAuthBearerCredential,
    HttpOAuthJwtConfig,
)
from EvernightAI.interface.http.errors import status_code_for_error
from EvernightAI.interface.http.sse import chat_stream_event_to_sse_event
from EvernightAI.interface.log_store import RECENT_LOG_STORE


def test_http_openapi_examples_are_try_it_ready() -> None:
    interface = create_interface(make_runtime())
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    chat_examples = schema["paths"]["/chat"]["post"]["requestBody"]["content"][
        "application/json"
    ]["examples"]
    context_stream_examples = schema["paths"]["/chat/context/stream"]["post"][
        "requestBody"
    ]["content"]["application/json"]["examples"]
    agent_stream_examples = schema["paths"]["/agent-runs/stream"]["post"][
        "requestBody"
    ]["content"]["application/json"]["examples"]
    session_chat_examples = schema["paths"]["/sessions/{session_id}/chat"]["post"][
        "requestBody"
    ]["content"]["application/json"]["examples"]
    chat_response_example = schema["paths"]["/chat"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["example"]
    chat_stream_example = schema["paths"]["/chat/stream"]["post"]["responses"]["200"][
        "content"
    ]["text/event-stream"]["example"]

    assert chat_examples["minimal"]["value"] == {
        "provider_id": "main",
        "request": {
            "model_id": "gpt-4.1-mini",
            "messages": [message_json("Hello, give me a short answer.")],
        },
    }
    assert context_stream_examples["streamReady"]["value"] == {
        "provider_id": "main",
        "context_id": "ctx-1",
        "model_id": "gpt-4.1-mini",
        "messages": [message_json("Stream the answer and save it.")],
        "metadata": {"request_id": "stream-1"},
    }
    assert agent_stream_examples["streamReady"]["value"] == {
        "provider_id": "main",
        "context_id": "ctx-1",
        "model_id": "gpt-4.1-mini",
        "messages": [message_json("Stream trace events while answering.")],
        "max_tool_rounds": 0,
        "metadata": {"request_id": "agent-stream-1"},
    }
    assert chat_examples["withReasoningEffort"]["value"]["request"]["metadata"] == {
        "reasoning_effort": "high"
    }
    assert session_chat_examples["withReasoningEffort"]["value"]["metadata"] == {
        "reasoning_effort": "high"
    }
    assert chat_response_example["message"]["content"] == [
        {"type": "text", "text": "Hello."}
    ]
    assert "url" not in chat_response_example["message"]["content"][0]
    assert "tool_calls" not in chat_response_example["message"]
    assert "event: chat.error" in chat_stream_example
    assert '"response_id":null' not in chat_stream_example
    assert "/data-analysis/statistics" in schema["paths"]
    assert "/data-analysis/analyze" in schema["paths"]


def test_http_maps_permission_denied_to_forbidden() -> None:
    assert status_code_for_error(AuthPermissionDeniedError("denied")) == 403


def test_http_app_can_set_custom_server_header() -> None:
    interface = create_interface(make_runtime())
    app = create_http_app(
        interface,
        close_on_shutdown=False,
        server_header="EvernightAdmin",
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["server"] == "EvernightAdmin"


def test_http_app_can_serve_static_frontend_without_shadowing_api(tmp_path) -> None:
    static_path = tmp_path / "dist"
    static_path.mkdir()
    (static_path / "index.html").write_text(
        "<!doctype html><title>Evernight Console</title>",
        encoding="utf-8",
    )
    assets_path = static_path / "assets"
    assets_path.mkdir()
    (assets_path / "app.js").write_text(
        "console.log('evernight')",
        encoding="utf-8",
    )
    interface = create_interface(make_runtime())
    app = create_http_app(
        interface,
        close_on_shutdown=False,
        static_files_path=static_path,
    )

    with TestClient(app) as client:
        index_response = client.get("/")
        asset_response = client.get("/assets/app.js")
        health_response = client.get("/health")

    assert index_response.status_code == 200
    assert "Evernight Console" in index_response.text
    assert asset_response.status_code == 200
    assert asset_response.text == "console.log('evernight')"
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}


def test_http_returns_forbidden_from_authorized_interface() -> None:
    interface = AuthorizedEvernightInterface(
        create_interface(make_runtime()),
        Authorizer(PermissionAuthPolicy()),
        Principal(principal_id="user-1"),
    )
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        response = client.get("/tools")

    assert response.status_code == 403
    assert_error_response(response.json(), "AuthPermissionDeniedError")


def test_http_api_key_auth_device_requires_credentials() -> None:
    app = create_http_app(
        create_interface(make_runtime()),
        auth_device=ApiKeyHttpAuthDevice(
            [
                HttpApiKeyCredential(
                    api_key="secret",
                    principal=Principal(
                        principal_id="user-1",
                        permissions=["tools:list"],
                    ),
                )
            ]
        ),
        authorized_interface_factory=lambda interface, principal: (
            AuthorizedEvernightInterface(
                interface,
                Authorizer(PermissionAuthPolicy()),
                principal,
            )
        ),
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        missing_response = client.get("/tools")
        invalid_response = client.get(
            "/tools",
            headers={"authorization": "Bearer wrong"},
        )
        valid_response = client.get(
            "/tools",
            headers={"authorization": "Bearer secret"},
        )

    assert missing_response.status_code == 401
    assert_error_response(missing_response.json(), "AuthRequiredError")
    assert invalid_response.status_code == 401
    assert_error_response(invalid_response.json(), "AuthRequiredError")
    assert valid_response.status_code == 200
    assert valid_response.json() == []


def test_http_api_key_auth_device_rejects_missing_permission() -> None:
    app = create_http_app(
        create_interface(make_runtime()),
        auth_device=ApiKeyHttpAuthDevice(
            [
                HttpApiKeyCredential(
                    api_key="secret",
                    principal=Principal(
                        principal_id="user-1",
                        permissions=["contexts:list"],
                    ),
                )
            ]
        ),
        authorized_interface_factory=lambda interface, principal: (
            AuthorizedEvernightInterface(
                interface,
                Authorizer(PermissionAuthPolicy()),
                principal,
            )
        ),
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        response = client.get("/tools", headers={"x-evernight-api-key": "secret"})

    assert response.status_code == 403
    assert_error_response(response.json(), "AuthPermissionDeniedError")


def test_http_oauth_bearer_auth_device_requires_access_token() -> None:
    app = create_http_app(
        create_interface(make_runtime()),
        auth_device=OAuthBearerHttpAuthDevice(
            [
                HttpOAuthBearerCredential(
                    access_token="token-1",
                    principal=Principal(
                        principal_id="oauth-user",
                        permissions=["tools:list"],
                    ),
                )
            ]
        ),
        authorized_interface_factory=lambda interface, principal: (
            AuthorizedEvernightInterface(
                interface,
                Authorizer(PermissionAuthPolicy()),
                principal,
            )
        ),
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        missing_response = client.get("/tools")
        invalid_response = client.get(
            "/tools",
            headers={"authorization": "Bearer wrong"},
        )
        valid_response = client.get(
            "/tools",
            headers={"authorization": "Bearer token-1"},
        )

    assert missing_response.status_code == 401
    assert_error_response(missing_response.json(), "AuthRequiredError")
    assert invalid_response.status_code == 401
    assert_error_response(invalid_response.json(), "AuthRequiredError")
    assert valid_response.status_code == 200
    assert valid_response.json() == []


def test_http_oauth_bearer_auth_device_maps_token_to_principal() -> None:
    device = OAuthBearerHttpAuthDevice(
        [
            HttpOAuthBearerCredential(
                access_token="token-1",
                principal=Principal(
                    principal_id="oauth-user",
                    permissions=["tools:list"],
                ),
            )
        ]
    )

    principal = device.principal("token-1")

    assert principal.principal_id == "oauth-user"
    assert principal.permissions == ["tools:list"]


def test_http_oauth_jwt_bearer_auth_device_validates_token_and_maps_claims() -> None:
    signing_key = "jwt-secret-with-at-least-32-bytes"
    device = OAuthJwtBearerHttpAuthDevice(
        HttpOAuthJwtConfig(
            issuer="https://idp.example.test",
            audience=["evernight-admin-api"],
            jwks_url="https://idp.example.test/.well-known/jwks.json",
            algorithms=["HS256"],
            roles_claim="realm_access.roles",
            role_permission_map={"evernight-admin": ["*"]},
            scope_permission_map={"evernight.tools": ["tools:list"]},
        ),
        jwk_client=StaticJwkClient(signing_key),
    )
    token = jwt.encode(
        {
            "iss": "https://idp.example.test",
            "aud": "evernight-admin-api",
            "sub": "admin-1",
            "exp": int(time.time()) + 60,
            "scope": "evernight.tools",
            "realm_access": {"roles": ["evernight-admin"]},
        },
        signing_key,
        algorithm="HS256",
    )

    principal = device.principal(token)

    assert principal.principal_id == "admin-1"
    assert principal.roles == ["evernight-admin"]
    assert principal.permissions == ["*", "tools:list"]
    assert principal.metadata["issuer"] == "https://idp.example.test"


def test_http_oauth_jwt_bearer_auth_device_rejects_invalid_claims() -> None:
    signing_key = "jwt-secret-with-at-least-32-bytes"
    device = OAuthJwtBearerHttpAuthDevice(
        HttpOAuthJwtConfig(
            issuer="https://idp.example.test",
            audience=["evernight-admin-api"],
            jwks_url="https://idp.example.test/.well-known/jwks.json",
            algorithms=["HS256"],
        ),
        jwk_client=StaticJwkClient(signing_key),
    )
    token = jwt.encode(
        {
            "iss": "https://other-idp.example.test",
            "aud": "evernight-admin-api",
            "sub": "admin-1",
            "exp": int(time.time()) + 60,
        },
        signing_key,
        algorithm="HS256",
    )

    try:
        device.principal(token)
    except AuthRequiredError:
        pass
    else:
        raise AssertionError("Expected AuthRequiredError")


def test_http_openapi_adds_security_scheme_when_auth_is_enabled() -> None:
    app = create_http_app(
        create_interface(make_runtime()),
        auth_device=ApiKeyHttpAuthDevice(
            [
                HttpApiKeyCredential(
                    api_key="secret",
                    principal=Principal(
                        principal_id="user-1",
                        permissions=["tools:list"],
                    ),
                )
            ]
        ),
        close_on_shutdown=False,
    )

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert schema["components"]["securitySchemes"]["EvernightBearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "OAuth Access Token",
        "description": (
            "Send an OAuth access token or API key as "
            "`Authorization: Bearer <token>`."
        ),
    }
    assert schema["components"]["securitySchemes"]["EvernightApiKey"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-Evernight-API-Key",
        "description": "Send the API key as `X-Evernight-API-Key: <api-key>`.",
    }
    assert schema["paths"]["/tools"]["get"]["security"] == [
        {"EvernightBearerAuth": []},
        {"EvernightApiKey": []},
    ]
    assert "security" not in schema["paths"]["/health"]["get"]


def test_http_app_exposes_chat_context_flow() -> None:
    provider = FakeProvider()
    interface = create_interface(make_runtime(provider=provider))
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        provider_response = client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        context_response = client.post(
            "/contexts",
            json={
                "context_id": "ctx-1",
                "messages": [message_json("Stored", role="system")],
            },
        )
        chat_response = client.post(
            "/chat/context",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Hello")],
                "metadata": {"request_id": "req-1"},
            },
        )
        stored_context_response = client.get("/contexts/ctx-1")
        delete_context_response = client.post("/contexts/ctx-1/delete")
        missing_context_response = client.get("/contexts/ctx-1")

    assert provider_response.status_code == 201
    assert provider_response.json() == {
        "provider_id": "provider-1",
        "name": "Fake",
        "type": "openai",
        "is_enabled": True,
        "model": {},
        "metadata": {},
    }
    assert context_response.status_code == 201
    assert chat_response.status_code == 200
    chat_body = chat_response.json()
    assert chat_body["message"]["content"][0]["text"] == "ok"
    assert "response_id" not in chat_body
    assert "usage" not in chat_body
    assert "tool_calls" not in chat_body["message"]
    assert "url" not in chat_body["message"]["content"][0]
    assert stored_context_response.status_code == 200
    assert [
        message["content"][0]["text"]
        for message in stored_context_response.json()["messages"]
    ] == ["Stored", "Hello", "ok"]
    assert delete_context_response.status_code == 204
    assert missing_context_response.status_code == 404
    assert_error_response(missing_context_response.json(), "ContextNotFoundError")
    assert provider.last_request is not None
    assert provider.last_request.metadata["request_id"] == "req-1"
    assert provider.last_request.metadata["context_id"] == "ctx-1"


def test_http_app_chat_context_retry_marks_old_branch() -> None:
    provider = FakeProvider()
    interface = create_interface(make_runtime(provider=provider))
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post(
            "/contexts",
            json={
                "context_id": "ctx-1",
                "messages": [
                    message_json("Original question"),
                    message_json("Bad answer", role="assistant"),
                    message_json("Follow-up"),
                ],
            },
        )
        chat_response = client.post(
            "/chat/context",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [],
                "retry_from_message_index": 1,
            },
        )
        stored_context_response = client.get("/contexts/ctx-1")

    assert chat_response.status_code == 200
    assert provider.last_request is not None
    assert [message_text(message) for message in provider.last_request.messages] == [
        "Original question",
    ]
    assert [
        message.get("status")
        for message in stored_context_response.json()["messages"]
    ] == [
        None,
        MessageStatus.REJECTED.value,
        MessageStatus.REJECTED.value,
        None,
    ]


def test_http_app_exposes_memory_and_tool_routes() -> None:
    interface = create_interface(make_runtime())
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        memory_response = client.post(
            "/memories",
            json={
                "memory_id": "mem-1",
                "content": "Use short answers",
                "kind": "preference",
                "scope": "user",
                "scope_id": "user-1",
                "priority": 3,
            },
        )
        memories_response = client.get("/memories")
        selected_response = client.post(
            "/memories/select",
            json={"scope": "user", "scope_id": "user-1", "limit": 1},
        )
        delete_memory_response = client.post("/memories/mem-1/delete")
        missing_memory_response = client.get("/memories/mem-1")
        tools_response = client.get("/tools")

    assert memory_response.status_code == 201
    assert memory_response.json()["memory_id"] == "mem-1"
    assert memories_response.status_code == 200
    assert [memory["memory_id"] for memory in memories_response.json()] == ["mem-1"]
    assert selected_response.status_code == 200
    assert [memory["memory_id"] for memory in selected_response.json()["memories"]] == [
        "mem-1"
    ]
    assert delete_memory_response.status_code == 204
    assert missing_memory_response.status_code == 404
    assert_error_response(missing_memory_response.json(), "MemoryNotFoundError")
    assert tools_response.status_code == 200
    assert tools_response.json() == []


def test_http_app_exposes_data_analysis_routes() -> None:
    async def statistics(
        request: DataStatisticsRequest,
    ) -> DataStatisticsResult:
        return DataStatisticsResult(
            source_id=request.source_id,
            rows=[
                DataStatisticsRow(
                    dimensions={"status": "paid"},
                    metrics={"order_count": 2, "revenue": 42},
                )
            ],
        )

    async def analyze(request: DataAnalysisRequest) -> DataAnalysisResult:
        return DataAnalysisResult(
            source_id=request.source_id,
            insights=[
                DataInsight(
                    kind=DataInsightKind.SUMMARY,
                    title="Revenue",
                    summary="Paid orders generated revenue.",
                )
            ],
            narrative="Paid orders generated revenue.",
        )

    runtime = make_runtime()
    runtime.data_analysis_register.register(
        DataSourceDefinition(
            source_id="orders",
            name="Orders",
            fields=[
                DataFieldDefinition(
                    field_id="status",
                    name="Status",
                    field_type=DataFieldType.STRING,
                ),
                DataFieldDefinition(
                    field_id="amount",
                    name="Amount",
                    field_type=DataFieldType.NUMBER,
                ),
            ],
            metrics=[
                DataMetricDefinition(
                    metric_id="order_count",
                    name="Order count",
                    aggregation=DataAggregation.COUNT,
                ),
                DataMetricDefinition(
                    metric_id="revenue",
                    name="Revenue",
                    aggregation=DataAggregation.SUM,
                    field_id="amount",
                ),
            ],
        ),
        statistics,
        analyze,
    )
    interface = create_interface(runtime)
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        sources_response = client.get("/data-analysis/sources")
        source_response = client.get("/data-analysis/sources/orders")
        fields_response = client.get("/data-analysis/sources/orders/fields")
        metrics_response = client.get("/data-analysis/sources/orders/metrics")
        statistics_response = client.post(
            "/data-analysis/statistics",
            json={
                "source_id": "orders",
                "metrics": ["order_count", "revenue"],
                "dimensions": ["status"],
            },
        )
        analysis_response = client.post(
            "/data-analysis/analyze",
            json={
                "source_id": "orders",
                "question": "Summarize revenue",
            },
        )
        missing_response = client.get("/data-analysis/sources/missing")

    assert sources_response.status_code == 200
    assert [source["source_id"] for source in sources_response.json()] == ["orders"]
    assert source_response.status_code == 200
    assert source_response.json()["name"] == "Orders"
    assert fields_response.status_code == 200
    assert [field["field_id"] for field in fields_response.json()] == [
        "status",
        "amount",
    ]
    assert metrics_response.status_code == 200
    assert [metric["metric_id"] for metric in metrics_response.json()] == [
        "order_count",
        "revenue",
    ]
    assert statistics_response.status_code == 200
    assert statistics_response.json()["rows"][0]["metrics"] == {
        "order_count": 2,
        "revenue": 42,
    }
    assert analysis_response.status_code == 200
    assert analysis_response.json()["insights"][0]["kind"] == "summary"
    assert missing_response.status_code == 404
    assert_error_response(missing_response.json(), "DataAnalysisNotFoundError")


def test_http_app_exposes_recent_log_routes() -> None:
    RECENT_LOG_STORE.clear()
    record = logging.LogRecord(
        name="EvernightAI.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=123,
        msg="log route ready",
        args=(),
        exc_info=None,
    )
    record.created = 1780000000.0
    RECENT_LOG_STORE.append(record)
    interface = create_interface(make_runtime())
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        list_response = client.get("/logs")
        filtered_response = client.get("/logs", params={"after": 1})
        clear_response = client.post("/logs/clear")
        cleared_response = client.get("/logs")

    assert list_response.status_code == 200
    assert list_response.json() == [
        {
            "index": 1,
            "timestamp": "2026-05-28T20:26:40Z",
            "level": "warning",
            "logger": "EvernightAI.test",
            "message": "log route ready",
            "module": "test_interface_http",
            "line": 123,
            "metadata": {},
        }
    ]
    assert filtered_response.status_code == 200
    assert filtered_response.json() == []
    assert clear_response.status_code == 204
    assert cleared_response.json() == []


def test_http_app_exposes_session_routes() -> None:
    interface = create_interface(make_runtime())
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        create_response = client.post(
            "/sessions",
            json={
                "session_id": "session-1",
                "title": "First chat",
                "context_id": "ctx-1",
                "provider_id": "provider-1",
                "model_id": "model-1",
                "metadata": {"source": "test"},
            },
        )
        list_response = client.get("/sessions")
        get_response = client.get("/sessions/session-1")
        created_context_response = client.get("/contexts/ctx-1")
        replace_response = client.put(
            "/sessions/session-1",
            json={
                "session_id": "ignored",
                "title": "Renamed chat",
                "context_id": "ctx-1",
                "provider_id": "provider-1",
                "model_id": "model-2",
            },
        )
        archive_response = client.post("/sessions/session-1/archive")
        delete_response = client.post("/sessions/session-1/delete")
        missing_response = client.get("/sessions/session-1")

    assert create_response.status_code == 201
    assert create_response.json()["status"] == "active"
    assert create_response.json()["context_id"] == "ctx-1"
    assert list_response.status_code == 200
    assert [session["session_id"] for session in list_response.json()] == [
        "session-1"
    ]
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "First chat"
    assert created_context_response.status_code == 200
    assert created_context_response.json()["metadata"] == {"session_id": "session-1"}
    assert replace_response.status_code == 200
    assert replace_response.json()["session_id"] == "session-1"
    assert replace_response.json()["title"] == "Renamed chat"
    assert replace_response.json()["model_id"] == "model-2"
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"
    assert delete_response.status_code == 204
    assert missing_response.status_code == 404
    assert_error_response(missing_response.json(), "SessionNotFoundError")


def test_http_validation_errors_use_error_response_shape() -> None:
    interface = create_interface(make_runtime())
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        response = client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
            },
        )

    assert response.status_code == 400
    body = response.json()
    assert_error_response(body, "ValidationError", message="Invalid request")
    assert body["error"]["detail"][0]["loc"] == ["body", "type"]


def test_http_domain_errors_use_error_response_shape() -> None:
    provider = FailingChatProvider()
    interface = create_interface(make_runtime(provider=provider))
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        chat_response = client.post(
            "/chat",
            json={
                "provider_id": "provider-1",
                "request": {
                    "model_id": "model-1",
                    "messages": [message_json("Hello")],
                },
            },
        )
        skill_response = client.get("/skills/missing")

    assert chat_response.status_code == 503
    assert_error_response(
        chat_response.json(),
        "ProviderUnavailableError",
        message="provider chat failed",
    )
    assert skill_response.status_code == 404
    assert_error_response(skill_response.json(), "SkillNotFoundError")


def test_http_app_chats_with_session_defaults_and_memory() -> None:
    provider = FakeProvider()
    runtime = make_runtime(provider=provider)
    interface = create_interface(runtime)
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post(
            "/memories",
            json={
                "memory_id": "session-memory",
                "content": "This session prefers concise replies",
                "scope": "session",
                "scope_id": "session-1",
            },
        )
        client.post(
            "/sessions",
            json={
                "session_id": "session-1",
                "title": "First chat",
                "context_id": "ctx-1",
                "provider_id": "provider-1",
                "model_id": "model-1",
            },
        )
        chat_response = client.post(
            "/sessions/session-1/chat",
            json={
                "messages": [message_json("Hello")],
                "metadata": {"request_id": "req-1"},
            },
        )
        context_response = client.get("/contexts/ctx-1")

    assert chat_response.status_code == 200
    assert chat_response.json()["session"]["session_id"] == "session-1"
    assert chat_response.json()["response"]["message"]["content"][0]["text"] == "ok"
    assert provider.last_request is not None
    assert [message_text(message) for message in provider.last_request.messages] == [
        "Relevant memory:\n- fact: This session prefers concise replies",
        "Hello",
    ]
    assert provider.last_request.metadata["session_id"] == "session-1"
    assert provider.last_request.metadata["request_id"] == "req-1"
    assert provider.last_request.metadata["context_id"] == "ctx-1"
    assert provider.last_request.metadata["memory_ids"] == ["session-memory"]
    assert [message["content"][0]["text"] for message in context_response.json()["messages"]] == [
        "Hello",
        "ok",
    ]


def test_http_app_starts_agent_run_from_session_defaults() -> None:
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    provider = FakeProvider()
    interface = create_interface(
        make_runtime(
            provider=provider,
            agent_state_register=state_register,
            agent_trace_register=trace_register,
        )
    )
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post(
            "/sessions",
            json={
                "session_id": "session-1",
                "title": "Agent chat",
                "context_id": "ctx-1",
                "provider_id": "provider-1",
                "model_id": "model-1",
            },
        )
        start_response = client.post(
            "/sessions/session-1/agent-runs",
            json={
                "messages": [message_json("Use the session")],
                "metadata": {"run_id": "run-1"},
            },
        )
        stored_response = client.get("/agent-runs/run-1")
        context_response = client.get("/contexts/ctx-1")

    assert start_response.status_code == 201
    assert start_response.json()["run_id"] == "run-1"
    assert start_response.json()["request"]["provider_id"] == "provider-1"
    assert start_response.json()["request"]["context_id"] == "ctx-1"
    assert start_response.json()["request"]["model_id"] == "model-1"
    assert start_response.json()["request"]["metadata"] == {
        "run_id": "run-1",
        "session_id": "session-1",
    }
    assert stored_response.status_code == 200
    assert stored_response.json()["status"] == "finished"
    assert provider.last_request is not None
    assert provider.last_request.metadata["session_id"] == "session-1"
    assert [message["content"][0]["text"] for message in context_response.json()["messages"]] == [
        "Use the session",
        "ok",
    ]


def test_http_app_exposes_skill_routes() -> None:
    async def summarize(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(
            render_id=request.render_id,
            skill_name=request.skill_name,
            messages=[
                make_message(str(request.variables["text"]), role=MessageRole.SYSTEM)
            ],
            metadata={"source": "fake"},
        )

    runtime = make_runtime()
    runtime.skill_register.register(
        SkillDefinition(
            name="summarize",
            description="Summarize text",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
            },
        ),
        summarize,
    )
    interface = create_interface(runtime)
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        skills_response = client.get("/skills")
        skill_response = client.get("/skills/summarize")
        supports_response = client.get(
            "/skills/summarize/supports",
            params={"capability": "chat"},
        )
        render_response = client.post(
            "/skills/summarize/render",
            json={
                "render_id": "skill-render-1",
                "variables": {"text": "hello"},
            },
        )
        default_render_response = client.post(
            "/skills/summarize/render",
            json={"variables": {"text": "default"}},
        )
        missing_response = client.get("/skills/missing")

    assert skills_response.status_code == 200
    assert [skill["name"] for skill in skills_response.json()] == ["summarize"]
    assert skill_response.status_code == 200
    assert skill_response.json()["name"] == "summarize"
    assert supports_response.status_code == 200
    assert supports_response.json() is False
    assert render_response.status_code == 200
    rendered = render_response.json()
    assert rendered["render_id"] == "skill-render-1"
    assert rendered["skill_name"] == "summarize"
    assert rendered["messages"][0]["role"] == "system"
    assert rendered["messages"][0]["content"][0]["text"] == "hello"
    assert rendered["metadata"] == {"source": "fake"}
    assert default_render_response.status_code == 200
    assert default_render_response.json()["render_id"] == "summarize-0"
    assert default_render_response.json()["messages"][0]["content"][0]["text"] == "default"
    assert missing_response.status_code == 404


def test_http_app_orchestrates_chat_skills() -> None:
    async def render_style(request: SkillRenderRequest) -> RenderedSkill:
        return RenderedSkill(
            render_id=request.render_id,
            skill_name=request.skill_name,
            messages=[
                make_message(
                    f"Use {request.variables['tone']} style",
                    role=MessageRole.SYSTEM,
                )
            ],
        )

    provider = FakeProvider()
    runtime = make_runtime(provider=provider)
    runtime.skill_register.register(
        SkillDefinition(
            name="style",
            description="Render style instructions",
            capabilities=[SkillCapability.CHAT],
        ),
        render_style,
    )
    interface = create_interface(runtime)
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        chat_response = client.post(
            "/chat",
            json={
                "provider_id": "provider-1",
                "request": {
                    "model_id": "model-1",
                    "messages": [message_json("Hello")],
                    "skills": [
                        {
                            "skill_name": "style",
                            "variables": {"tone": "concise"},
                        }
                    ],
                },
            },
        )

    assert chat_response.status_code == 200
    assert provider.last_request is not None
    assert [
        message["content"][0]["text"]
        for message in [
            message.model_dump(mode="json") for message in provider.last_request.messages
        ]
    ] == ["Use concise style", "Hello"]
    assert provider.last_request.skills is None


def test_http_app_exposes_provider_management_routes() -> None:
    interface = create_interface(make_runtime(provider=FakeProvider()))
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
                "api_key": "secret",
                "model": {
                    "model-1": {
                        "model_id": "model-1",
                        "capabilities": ["chat"],
                    }
                },
            },
        )
        providers_response = client.get("/providers")
        models_response = client.get("/providers/provider-1/models")
        model_response = client.get("/providers/provider-1/models/model-1")
        supports_response = client.get(
            "/providers/provider-1/supports",
            params={"capability": "chat"},
        )
        delete_response = client.post("/providers/provider-1/delete")
        deleted_providers_response = client.get("/providers")
        missing_response = client.get("/providers/provider-1/models")

    assert providers_response.status_code == 200
    assert providers_response.json() == [
        {
            "provider_id": "provider-1",
            "name": "Fake",
            "type": "openai",
            "is_enabled": True,
            "model": {
                "model-1": {
                    "model_id": "model-1",
                    "timeout": "PT30S",
                    "capabilities": ["chat"],
                    "metadata": {},
                }
            },
            "metadata": {},
        }
    ]
    assert models_response.status_code == 200
    assert [model["model_id"] for model in models_response.json()] == ["model-1"]
    assert model_response.status_code == 200
    assert model_response.json()["model_id"] == "model-1"
    assert supports_response.status_code == 200
    assert supports_response.json() is True
    assert delete_response.status_code == 204
    assert deleted_providers_response.json() == []
    assert missing_response.status_code == 404


def test_http_app_exposes_chat_stream_route() -> None:
    provider = FakeProvider(
        stream_events=[
            ChatStreamEvent(
                event_type=ChatStreamEventType.RAW,
                response_id="evt-1",
                raw_event="message",
                raw_data={"delta": "hello"},
            ),
            ChatStreamEvent(event_type=ChatStreamEventType.DONE),
        ]
    )
    interface = create_interface(make_runtime(provider=provider))
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        stream_response = client.post(
            "/chat/stream",
            json={
                "provider_id": "provider-1",
                "request": {
                    "model_id": "model-1",
                    "messages": [message_json("Hello")],
                },
            },
        )

    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert "event: message" in stream_response.text
    assert "id: evt-1" in stream_response.text
    assert 'data: {"delta":"hello"}' in stream_response.text
    assert "event: done" in stream_response.text
    assert "data: [DONE]" in stream_response.text
    assert provider.last_request is not None
    assert provider.last_request.model_id == "model-1"


def test_http_app_exposes_chat_context_stream_route() -> None:
    provider = FakeProvider(
        stream_events=[
            ChatStreamEvent(
                event_type=ChatStreamEventType.MESSAGE_DELTA,
                response_id="resp-1",
                text_delta="hello",
            ),
            ChatStreamEvent(event_type=ChatStreamEventType.DONE),
        ]
    )
    interface = create_interface(make_runtime(provider=provider))
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post(
            "/contexts",
            json={
                "context_id": "ctx-1",
                "messages": [message_json("Stored", role="system")],
            },
        )
        stream_response = client.post(
            "/chat/context/stream",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Hello")],
            },
        )
        context_response = client.get("/contexts/ctx-1")

    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert "event: chat.message_delta" in stream_response.text
    assert "event: done" in stream_response.text
    assert provider.last_request is not None
    assert [message_text(message) for message in provider.last_request.messages] == [
        "Stored",
        "Hello",
    ]
    assert [
        message["content"][0]["text"]
        for message in context_response.json()["messages"]
    ] == ["Stored", "Hello", "hello"]


def test_http_chat_stream_events_are_encoded_as_sse() -> None:
    sse_event = chat_stream_event_to_sse_event(
        ChatStreamEvent(
            event_type=ChatStreamEventType.MESSAGE_DELTA,
            response_id="resp-1",
            text_delta="hello",
        )
    )

    assert sse_event.event == "chat.message_delta"
    assert sse_event.event_id == "resp-1"
    assert json.loads(sse_event.data)["text_delta"] == "hello"


def test_http_chat_stream_encodes_provider_errors_as_sse() -> None:
    interface = create_interface(make_runtime(provider=FailingStreamProvider()))
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        stream_response = client.post(
            "/chat/stream",
            json={
                "provider_id": "provider-1",
                "request": {
                    "model_id": "model-1",
                    "messages": [message_json("Hello")],
                },
            },
        )

    assert stream_response.status_code == 200
    assert "event: chat.error" in stream_response.text
    assert "ProviderUnavailableError" in stream_response.text
    assert "provider stream failed" in stream_response.text
    assert '"response_id":null' not in stream_response.text
    assert '"model_id":null' not in stream_response.text


def test_http_app_exposes_persisted_agent_run_routes() -> None:
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    interface = create_interface(
        make_runtime(
            provider=FakeProvider(),
            agent_state_register=state_register,
            agent_trace_register=trace_register,
        )
    )
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post("/contexts", json={"context_id": "ctx-1"})
        start_response = client.post(
            "/agent-runs",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Hello")],
                "metadata": {"run_id": "run-1"},
            },
        )
        get_response = client.get("/agent-runs/run-1")
        list_response = client.get("/agent-runs")
        trace_response = client.get("/agent-runs/run-1/trace")

    assert start_response.status_code == 201
    assert start_response.json()["run_id"] == "run-1"
    assert start_response.json()["status"] == "finished"
    assert get_response.status_code == 200
    assert get_response.json()["run_id"] == "run-1"
    assert list_response.status_code == 200
    assert [state["run_id"] for state in list_response.json()] == ["run-1"]
    assert trace_response.status_code == 200
    assert [event["event_type"] for event in trace_response.json()] == [
        "run_started",
        "chat_completed",
        "run_stopped",
    ]


def test_http_app_streams_agent_trace_events() -> None:
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    interface = create_interface(
        make_runtime(
            provider=FakeProvider(),
            agent_state_register=state_register,
            agent_trace_register=trace_register,
        )
    )
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post("/contexts", json={"context_id": "ctx-1"})
        with client.stream(
            "POST",
            "/agent-runs/stream",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Hello")],
                "metadata": {"run_id": "run-1"},
            },
        ) as stream_response:
            body = stream_response.read().decode("utf-8")
            content_type = stream_response.headers["content-type"]
        state_response = client.get("/agent-runs/run-1")
        trace_response = client.get("/agent-runs/run-1/trace")

    events = parse_sse_events(body)

    assert content_type.startswith("text/event-stream")
    assert [event["event_type"] for event in events] == [
        "run_started",
        "chat_completed",
        "run_stopped",
    ]
    assert [event["summary"] for event in events] == [
        "Agent run started",
        "Model response received",
        "Agent run stopped: finished",
    ]
    assert events[-1]["metadata"]["reason"] == "finished"
    assert state_response.status_code == 200
    assert state_response.json()["status"] == "finished"
    assert [event["event_type"] for event in trace_response.json()] == [
        "run_started",
        "chat_completed",
        "run_stopped",
    ]
    assert [event["summary"] for event in trace_response.json()] == [
        "Agent run started",
        "Model response received",
        "Agent run stopped: finished",
    ]


def test_http_app_streams_agent_chat_delta_events() -> None:
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    interface = create_interface(
        make_runtime(
            provider=FakeProvider(
                stream_events=[
                    ChatStreamEvent(
                        event_type=ChatStreamEventType.MESSAGE_DELTA,
                        text_delta="hel",
                    ),
                    ChatStreamEvent(
                        event_type=ChatStreamEventType.MESSAGE_DELTA,
                        text_delta="lo",
                    ),
                    ChatStreamEvent(event_type=ChatStreamEventType.DONE),
                ]
            ),
            agent_state_register=state_register,
            agent_trace_register=trace_register,
        )
    )
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post("/contexts", json={"context_id": "ctx-1"})
        with client.stream(
            "POST",
            "/agent-runs/stream",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Hello")],
                "metadata": {"run_id": "run-1", "stream": True},
            },
        ) as stream_response:
            body = stream_response.read().decode("utf-8")

    events = parse_sse_events(body)

    assert [event["event_type"] for event in events] == [
        "run_started",
        "chat_delta",
        "chat_delta",
        "chat_completed",
        "run_stopped",
    ]
    assert [event["text_delta"] for event in events if event.get("text_delta")] == [
        "hel",
        "lo",
    ]
    assert events[3]["message"]["content"][0]["text"] == "hello"


def test_http_agent_stream_encodes_provider_errors_as_sse() -> None:
    state_register = InMemoryAgentRunStateRegister()
    trace_register = InMemoryAgentTraceRegister()
    interface = create_interface(
        make_runtime(
            provider=FailingChatProvider(),
            agent_state_register=state_register,
            agent_trace_register=trace_register,
        )
    )
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post("/contexts", json={"context_id": "ctx-1"})
        stream_response = client.post(
            "/agent-runs/stream",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Hello")],
            },
        )

    assert stream_response.status_code == 200
    assert "event: run_started" in stream_response.text
    assert "event: error" in stream_response.text
    assert "ProviderUnavailableError" in stream_response.text
    assert "provider chat failed" in stream_response.text


def test_http_app_streams_agent_pause_for_tool_approval() -> None:
    tool_executed = False

    async def write_file(_arguments: dict[str, object]) -> dict[str, object]:
        nonlocal tool_executed
        tool_executed = True
        return {"written": True}

    runtime = make_runtime(
        provider=SensitiveToolProvider(),
        agent_state_register=InMemoryAgentRunStateRegister(),
        agent_trace_register=InMemoryAgentTraceRegister(),
    )
    tool = sensitive_tool_definition()
    runtime.tool_register.register(tool, write_file)
    interface = create_interface(runtime)
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post("/contexts", json={"context_id": "ctx-1"})
        with client.stream(
            "POST",
            "/agent-runs/stream",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Write a file")],
                "tools": [tool.model_dump(mode="json")],
                "pause_on_approval": True,
            },
        ) as stream_response:
            body = stream_response.read().decode("utf-8")

    events = parse_sse_events(body)

    assert [event["event_type"] for event in events] == [
        "run_started",
        "chat_completed",
        "tool_approval_requested",
        "run_paused",
    ]
    assert [event["summary"] for event in events] == [
        "Agent run started",
        "Model response received",
        "Tool approval requested for write_file",
        "Agent run paused: tool_approval_required",
    ]
    assert events[2]["approval_request"]["tool_name"] == "write_file"
    assert events[3]["metadata"]["reason"] == "tool_approval_required"
    assert tool_executed is False


def test_http_app_approves_pending_agent_run_without_manual_payload() -> None:
    tool_executed = False

    async def write_file(_arguments: dict[str, object]) -> dict[str, object]:
        nonlocal tool_executed
        tool_executed = True
        return {"written": True}

    provider = SensitiveThenFinalProvider()
    runtime = make_runtime(
        provider=provider,
        agent_state_register=InMemoryAgentRunStateRegister(),
        agent_trace_register=InMemoryAgentTraceRegister(),
    )
    tool = sensitive_tool_definition()
    runtime.tool_register.register(tool, write_file)
    interface = create_interface(runtime)
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        client.post(
            "/providers",
            json={
                "provider_id": "provider-1",
                "name": "Fake",
                "type": "openai",
            },
        )
        client.post("/contexts", json={"context_id": "ctx-1"})
        start_response = client.post(
            "/agent-runs",
            json={
                "provider_id": "provider-1",
                "context_id": "ctx-1",
                "model_id": "model-1",
                "messages": [message_json("Write a file")],
                "tools": [tool.model_dump(mode="json")],
                "pause_on_approval": True,
                "metadata": {"run_id": "run-1"},
            },
        )
        approve_response = client.post("/agent-runs/run-1/approve-pending")

    assert start_response.status_code == 201
    assert start_response.json()["status"] == "paused"
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "finished"
    assert tool_executed is True
    assert [message.role for message in provider.requests[1].messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
    ]


def test_http_app_maps_domain_errors() -> None:
    interface = create_interface(make_runtime())
    app = create_http_app(interface, close_on_shutdown=False)

    with TestClient(app) as client:
        missing_context_response = client.get("/contexts/missing")
        missing_agent_storage_response = client.get("/agent-runs/missing")

    assert missing_context_response.status_code == 404
    assert missing_context_response.json()["error"]["type"] == "ContextNotFoundError"
    assert missing_agent_storage_response.status_code == 409
    assert missing_agent_storage_response.json()["error"]["type"] == "AgentStateError"


def make_runtime(
    *,
    provider: ProviderInstanceProtocol | None = None,
    agent_state_register: AgentRunStateRegisterProtocol | None = None,
    agent_trace_register: AgentTraceRegisterProtocol | None = None,
) -> RuntimeKernel:
    async def build_provider(_config: ProviderConfig) -> ProviderInstanceProtocol:
        return provider or FakeProvider()

    provider_factory = ProviderFactory()
    provider_factory.register(ProviderType.OPENAI, build_provider)
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
        agent_state_register=agent_state_register,
        agent_trace_register=agent_trace_register,
    )


def message_json(text: str, *, role: str = "user") -> dict[str, object]:
    return {
        "role": role,
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ],
    }


def make_message(text: str, *, role: MessageRole = MessageRole.USER) -> Content:
    return Content(
        role=role,
        content=[ContentPart(type=ContentPartType.TEXT, text=text)],
    )


def message_text(message: Content) -> str:
    if not message.content or message.content[0].text is None:
        return ""

    return message.content[0].text


def parse_sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        data_lines = [
            line.removeprefix("data: ")
            for line in block.splitlines()
            if line.startswith("data: ")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))

    return events


def assert_error_response(
    body: dict[str, Any],
    error_type: str,
    *,
    message: str | None = None,
) -> None:
    assert set(body) == {"error"}
    assert body["error"]["type"] == error_type
    if message is not None:
        assert body["error"]["message"] == message
    assert "detail" in body["error"]


def sensitive_tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name="write_file",
        description="Write a file",
        parameters_schema={"type": "object"},
        permissions=[ToolPermission.FILESYSTEM, ToolPermission.WRITE],
        safety_level=ToolSafetyLevel.SENSITIVE,
    )


class FakeProvider(ProviderInstanceProtocol):
    def __init__(self, stream_events: list[ChatStreamEvent] | None = None) -> None:
        self.last_request: ChatRequest | None = None
        self.stream_events = stream_events or []

    async def list_models(self) -> list[ProviderModelConfig]:
        return [
            ProviderModelConfig(
                model_id="model-1",
                capabilities=[ProviderModelCapability.CHAT],
            )
        ]

    async def get_model(self, model_id: str) -> ProviderModelConfig:
        return ProviderModelConfig(
            model_id=model_id,
            capabilities=[ProviderModelCapability.CHAT],
        )

    async def supports(self, capability: ProviderModelCapability) -> bool:
        return capability is ProviderModelCapability.CHAT

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_request = request
        return ChatResponse(
            model_id=request.model_id,
            message=make_message("ok", role=MessageRole.ASSISTANT),
            finish_reason="stop",
        )

    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        self.last_request = request
        return EventStream(self.stream_events)

    async def close(self) -> None:
        pass


class FailingStreamProvider(FakeProvider):
    async def chat_stream(self, request: ChatRequest) -> ChatStreamProtocol:
        self.last_request = request
        return FailingChatStream(
            ProviderUnavailableError("provider stream failed")
        )


class FailingChatProvider(FakeProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_request = request
        raise ProviderUnavailableError("provider chat failed")


class SensitiveToolProvider(FakeProvider):
    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_request = request
        return ChatResponse(
            model_id=request.model_id,
            message=Content(
                role=MessageRole.ASSISTANT,
                tool_calls=[
                    ToolCall(
                        tool_call_id="tool-call-1",
                        tool_call={
                            "name": "write_file",
                            "arguments": {"path": "note.txt"},
                        },
                    )
                ],
            ),
            finish_reason="tool_calls",
        )


class SensitiveThenFinalProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_request = request
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatResponse(
                model_id=request.model_id,
                message=Content(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            tool_call_id="tool-call-1",
                            tool_call={
                                "name": "write_file",
                                "arguments": {"path": "note.txt"},
                            },
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )

        return ChatResponse(
            model_id=request.model_id,
            message=make_message("Written", role=MessageRole.ASSISTANT),
            finish_reason="stop",
        )


class InMemoryAgentRunStateRegister(AgentRunStateRegisterProtocol):
    def __init__(self) -> None:
        self.states: dict[str, AgentRunState] = {}

    def save_state(self, state: AgentRunState) -> None:
        self.states[state.run_id] = state

    def get_state(self, run_id: str) -> AgentRunState:
        try:
            return self.states[run_id]
        except KeyError as exc:
            raise AgentStateError(f"The agent run state {run_id} is not found") from exc

    def list_states(self) -> list[AgentRunState]:
        return list(self.states.values())

    def delete_state(self, run_id: str) -> None:
        self.states.pop(run_id, None)


class InMemoryAgentTraceRegister(AgentTraceRegisterProtocol):
    def __init__(self) -> None:
        self.events: dict[str, list[AgentTraceEvent]] = {}

    def append_event(self, run_id: str, event: AgentTraceEvent) -> None:
        self.events.setdefault(run_id, []).append(event)

    def list_events(self, run_id: str) -> list[AgentTraceEvent]:
        return list(self.events.get(run_id, []))

    def clear_events(self, run_id: str) -> None:
        self.events.pop(run_id, None)


class EventStream:
    def __init__(self, events: list[ChatStreamEvent]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ChatStreamEvent]:
        for event in self._events:
            yield event


class FailingChatStream:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ChatStreamEvent]:
        raise self._error
        yield ChatStreamEvent(event_type=ChatStreamEventType.DONE)


class StaticJwkClient:
    def __init__(self, key: str) -> None:
        self._key = key

    def get_signing_key_from_jwt(self, token: str):
        return StaticSigningKey(self._key)


class StaticSigningKey:
    def __init__(self, key: str) -> None:
        self.key = key
