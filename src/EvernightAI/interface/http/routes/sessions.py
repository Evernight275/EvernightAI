from typing import Annotated

from fastapi import APIRouter, Body, Query, Response, status

from EvernightAI.core.schema.agent import AgentRunState
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
    SessionChatResult,
    SessionStatus,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.template import (
    AGENT_RUN_STATE_RESPONSE_EXAMPLE,
    SESSION_AGENT_RUN_EXAMPLES,
    SESSION_CHAT_RESPONSE_EXAMPLE,
    SESSION_CHAT_EXAMPLES,
    SESSION_EXAMPLES,
)


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post(
    "",
    response_model=Session,
    response_model_exclude_none=True,
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
    response_model_exclude_none=True,
    summary="List sessions",
    operation_id="list_sessions",
)
async def list_sessions(
    interface: InterfaceDependency,
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    owner_id: str | None = Query(default=None),
    status_filter: SessionStatus | None = Query(default=None, alias="status"),
    provider_id: str | None = Query(default=None),
    model_id: str | None = Query(default=None),
) -> list[Session]:
    return await interface.sessions.list_sessions(
        cursor=cursor,
        limit=limit,
        owner_id=owner_id,
        status=status_filter,
        provider_id=provider_id,
        model_id=model_id,
    )


@router.get(
    "/{session_id}",
    response_model=Session,
    response_model_exclude_none=True,
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
    response_model_exclude_none=True,
    summary="Chat with a session",
    description=(
        "Use the session's context, provider, and model. New user and assistant "
        "messages are persisted to the session context."
    ),
    operation_id="chat_with_session",
    responses={200: SESSION_CHAT_RESPONSE_EXAMPLE},
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
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="Start a session agent run",
    description="Start a multi-step agent run using the session's provider, model, and context.",
    operation_id="start_agent_run_for_session",
    responses={201: AGENT_RUN_STATE_RESPONSE_EXAMPLE},
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
    response_model_exclude_none=True,
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
    response_model_exclude_none=True,
    summary="Archive a session",
    operation_id="archive_session",
)
async def archive_session(
    session_id: str,
    interface: InterfaceDependency,
) -> Session:
    return await interface.sessions.archive_session(session_id)


@router.post(
    "/{session_id}/delete",
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
