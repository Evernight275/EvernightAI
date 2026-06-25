from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi

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
from EvernightAI.interface.http.routes.health import router as health_router
from EvernightAI.interface.http.routes.memories import router as memories_router
from EvernightAI.interface.http.routes.providers import router as providers_router
from EvernightAI.interface.http.routes.sessions import router as sessions_router
from EvernightAI.interface.http.routes.skills import router as skills_router
from EvernightAI.interface.http.routes.tools import router as tools_router
from EvernightAI.interface.http.template import API_DESCRIPTION, OPENAPI_TAGS


HTTP_BEARER_SECURITY_SCHEME = "EvernightBearerAuth"
HTTP_HEADER_API_KEY_SECURITY_SCHEME = "EvernightApiKey"


def create_http_app(
    interface: EvernightInterfaceProtocol,
    *,
    auth_device: HttpAuthDeviceProtocol | None = None,
    authorized_interface_factory: AuthorizedHttpInterfaceFactoryProtocol | None = None,
    close_on_shutdown: bool = True,
    startup_handlers: list[Callable[[], Awaitable[None]]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
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
    app.state.authorized_interface_factory = (
        authorized_interface_factory or _identity_authorized_interface
    )
    if auth_device is not None:
        app.openapi = _secured_openapi_factory(app)
    app.add_exception_handler(EvernightAIError, handle_evernight_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.include_router(health_router)
    app.include_router(providers_router)
    app.include_router(contexts_router)
    app.include_router(memories_router)
    app.include_router(sessions_router)
    app.include_router(skills_router)
    app.include_router(tools_router)
    app.include_router(chat_router)
    app.include_router(agent_runs_router)

    return app


def _identity_authorized_interface(
    interface: EvernightInterfaceProtocol,
    _principal: Principal,
) -> EvernightInterfaceProtocol:
    return interface


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
            "bearerFormat": "API Key",
            "description": "Send the API key as `Authorization: Bearer <api-key>`.",
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
            if path == "/health":
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
