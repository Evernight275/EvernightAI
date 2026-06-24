from typing import Annotated

from fastapi import APIRouter, Body, Response, status

from EvernightAI.core.schema.agent import AgentRunState
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
    SessionChatResult,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.template import (
    SESSION_AGENT_RUN_EXAMPLES,
    SESSION_CHAT_EXAMPLES,
    SESSION_EXAMPLES,
)


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post(
    "",
    response_model=Session,
    status_code=status.HTTP_201_CREATED,
    summary="Create a session",
    description=(
        "Create a user-facing conversation. The session stores the context id, "
        "provider id, and model id used by session chat."
    ),
    operation_id="create_session",
)
async def create_session(
    session: Annotated[
        Session,
        Body(openapi_examples=SESSION_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> Session:
    return await interface.sessions.create_session(session)


@router.get(
    "",
    response_model=list[Session],
    summary="List sessions",
    operation_id="list_sessions",
)
async def list_sessions(interface: InterfaceDependency) -> list[Session]:
    return await interface.sessions.list_sessions()


@router.get(
    "/{session_id}",
    response_model=Session,
    summary="Get a session",
    operation_id="get_session",
)
async def get_session(
    session_id: str,
    interface: InterfaceDependency,
) -> Session:
    return await interface.sessions.get_session(session_id)


@router.post(
    "/{session_id}/chat",
    response_model=SessionChatResult,
    summary="Chat with a session",
    description=(
        "Use the session's context, provider, and model. New user and assistant "
        "messages are persisted to the session context."
    ),
    operation_id="chat_with_session",
)
async def chat_with_session(
    session_id: str,
    request: Annotated[
        SessionChatRequest,
        Body(openapi_examples=SESSION_CHAT_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> SessionChatResult:
    return await interface.sessions.chat_with_session(session_id, request)


@router.post(
    "/{session_id}/agent-runs",
    response_model=AgentRunState,
    status_code=status.HTTP_201_CREATED,
    summary="Start a session agent run",
    description="Start a multi-step agent run using the session's provider, model, and context.",
    operation_id="start_agent_run_for_session",
)
async def start_agent_run_for_session(
    session_id: str,
    request: Annotated[
        SessionAgentRunRequest,
        Body(openapi_examples=SESSION_AGENT_RUN_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> AgentRunState:
    return await interface.sessions.start_agent_run_for_session(session_id, request)


@router.put(
    "/{session_id}",
    response_model=Session,
    summary="Replace a session",
    operation_id="replace_session",
)
async def replace_session(
    session_id: str,
    session: Annotated[
        Session,
        Body(openapi_examples=SESSION_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> Session:
    updated = (
        session
        if session.session_id == session_id
        else session.model_copy(update={"session_id": session_id})
    )
    return await interface.sessions.replace_session(updated)


@router.post(
    "/{session_id}/archive",
    response_model=Session,
    summary="Archive a session",
    operation_id="archive_session",
)
async def archive_session(
    session_id: str,
    interface: InterfaceDependency,
) -> Session:
    return await interface.sessions.archive_session(session_id)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a session",
    operation_id="delete_session",
)
async def delete_session(
    session_id: str,
    interface: InterfaceDependency,
) -> None:
    await interface.sessions.delete_session(session_id)
