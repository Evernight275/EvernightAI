from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from EvernightAI.core.error.base import EvernightAIError
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.interface.http.errors import handle_evernight_error
from EvernightAI.interface.http.routes.agent_runs import router as agent_runs_router
from EvernightAI.interface.http.routes.chat import router as chat_router
from EvernightAI.interface.http.routes.contexts import router as contexts_router
from EvernightAI.interface.http.routes.health import router as health_router
from EvernightAI.interface.http.routes.memories import router as memories_router
from EvernightAI.interface.http.routes.providers import router as providers_router
from EvernightAI.interface.http.routes.skills import router as skills_router
from EvernightAI.interface.http.routes.tools import router as tools_router


def create_http_app(
    interface: EvernightInterfaceProtocol,
    *,
    close_on_shutdown: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if close_on_shutdown:
                await interface.close()

    app = FastAPI(title="EvernightAI", lifespan=lifespan)
    app.state.interface = interface
    app.add_exception_handler(EvernightAIError, handle_evernight_error)
    app.include_router(health_router)
    app.include_router(providers_router)
    app.include_router(contexts_router)
    app.include_router(memories_router)
    app.include_router(skills_router)
    app.include_router(tools_router)
    app.include_router(chat_router)
    app.include_router(agent_runs_router)

    return app
