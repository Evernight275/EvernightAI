from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from EvernightAI.core.error.base import EvernightAIError
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.schema.auth import Principal
from EvernightAI.interface.http.errors import (
    handle_evernight_error,
    handle_request_validation_error,
)
from EvernightAI.interface.http.protocol import (
    AuthorizedHttpInterfaceFactoryProtocol,
    HttpAuthDeviceProtocol,
)
from EvernightAI.interface.http.routes.agent_runs import router as agent_runs_router
from EvernightAI.interface.http.routes.chat import router as chat_router
from EvernightAI.interface.http.routes.contexts import router as contexts_router
from EvernightAI.interface.http.routes.data_analysis import (
    router as data_analysis_router,
)
from EvernightAI.interface.http.routes.health import router as health_router
from EvernightAI.interface.http.routes.logs import router as logs_router
from EvernightAI.interface.http.routes.memories import router as memories_router
from EvernightAI.interface.http.routes.providers import router as providers_router
from EvernightAI.interface.http.routes.sessions import router as sessions_router
from EvernightAI.interface.http.routes.skills import router as skills_router
from EvernightAI.interface.http.routes.tools import router as tools_router
from EvernightAI.interface.http.routes.websocket import router as websocket_router
from EvernightAI.interface.http.template import API_DESCRIPTION, OPENAPI_TAGS
from EvernightAI.interface.http.websocket import WebSocketConnectionManager


HTTP_BEARER_SECURITY_SCHEME = "EvernightBearerAuth"
HTTP_HEADER_API_KEY_SECURITY_SCHEME = "EvernightApiKey"
LOGGER = logging.getLogger("EvernightAI.interface.http.access")
REQUEST_ID_HEADER = "X-Request-ID"


def create_http_app(
    interface: EvernightInterfaceProtocol,
    *,
    auth_device: HttpAuthDeviceProtocol | None = None,
    authorized_interface_factory: AuthorizedHttpInterfaceFactoryProtocol | None = None,
    close_on_shutdown: bool = True,
    initialize_handler: Callable[[], Awaitable[None]] | None = None,
    readiness_checker: Callable[[], bool] | None = None,
    startup_handlers: list[Callable[[], Awaitable[None]]] | None = None,
    server_header: str | None = None,
    static_files_path: str | Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            if initialize_handler is not None:
                await initialize_handler()
            for handler in startup_handlers or []:
                await handler()
            yield
        finally:
            if close_on_shutdown:
                await interface.close()

    app = FastAPI(
        title="EvernightAI",
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.state.interface = interface
    app.state.auth_device = auth_device
    app.state.readiness_checker = readiness_checker or _always_ready
    app.state.websocket_manager = WebSocketConnectionManager()
    app.state.authorized_interface_factory = (
        authorized_interface_factory or _identity_authorized_interface
    )
    _add_request_context_middleware(app)
    if server_header is not None and server_header != "":
        _add_server_header_middleware(app, server_header)
    if auth_device is not None:
        app.openapi = _secured_openapi_factory(app)
    app.add_exception_handler(EvernightAIError, handle_evernight_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.include_router(health_router)
    app.include_router(logs_router)
    app.include_router(providers_router)
    app.include_router(contexts_router)
    app.include_router(memories_router)
    app.include_router(data_analysis_router)
    app.include_router(sessions_router)
    app.include_router(skills_router)
    app.include_router(tools_router)
    app.include_router(chat_router)
    app.include_router(agent_runs_router)
    app.include_router(websocket_router)
    if static_files_path is not None:
        app.mount(
            "/",
            StaticFiles(directory=Path(static_files_path), html=True),
            name="frontend",
        )

    return app


def _add_server_header_middleware(app: FastAPI, server_header: str) -> None:
    @app.middleware("http")
    async def add_server_header(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["server"] = server_header
        return response


def _add_request_context_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            session_id, run_id = _resource_ids(request.url.path)
            LOGGER.info(
                "HTTP request completed",
                extra={
                    "request_id": request_id,
                    "session_id": session_id,
                    "run_id": run_id,
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code if response else 500,
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                },
            )
            if response is not None:
                response.headers[REQUEST_ID_HEADER] = request_id


def _resource_ids(path: str) -> tuple[str | None, str | None]:
    parts = [part for part in path.split("/") if part]
    session_id = parts[1] if len(parts) > 1 and parts[0] == "sessions" else None
    run_id = parts[1] if len(parts) > 1 and parts[0] == "agent-runs" else None
    return session_id, run_id


def _identity_authorized_interface(
    interface: EvernightInterfaceProtocol,
    _principal: Principal,
) -> EvernightInterfaceProtocol:
    return interface


def _always_ready() -> bool:
    return True


def _secured_openapi_factory(app: FastAPI):
    def openapi() -> dict[str, object]:
        if app.openapi_schema is not None:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes[HTTP_BEARER_SECURITY_SCHEME] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "OAuth Access Token",
            "description": (
                "Send an OAuth access token or API key as "
                "`Authorization: Bearer <token>`."
            ),
        }
        security_schemes[HTTP_HEADER_API_KEY_SECURITY_SCHEME] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-Evernight-API-Key",
            "description": (
                "Send the API key as `X-Evernight-API-Key: <api-key>`."
            ),
        }
        for path, methods in schema.get("paths", {}).items():
            if path in {"/health", "/ready"}:
                continue
            for operation in methods.values():
                if isinstance(operation, dict):
                    operation["security"] = [
                        {HTTP_BEARER_SECURITY_SCHEME: []},
                        {HTTP_HEADER_API_KEY_SECURITY_SCHEME: []},
                    ]

        app.openapi_schema = schema
        return schema

    return openapi
