from fastapi import APIRouter, Response, status

from EvernightAI.core.schema.agent import AgentRunState
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
    SessionChatResult,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post(
    "",
    response_model=Session,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    session: Session,
    interface: InterfaceDependency,
) -> Session:
    return await interface.sessions.create_session(session)


@router.get("", response_model=list[Session])
async def list_sessions(interface: InterfaceDependency) -> list[Session]:
    return await interface.sessions.list_sessions()


@router.get("/{session_id}", response_model=Session)
async def get_session(
    session_id: str,
    interface: InterfaceDependency,
) -> Session:
    return await interface.sessions.get_session(session_id)


@router.post("/{session_id}/chat", response_model=SessionChatResult)
async def chat_with_session(
    session_id: str,
    request: SessionChatRequest,
    interface: InterfaceDependency,
) -> SessionChatResult:
    return await interface.sessions.chat_with_session(session_id, request)


@router.post(
    "/{session_id}/agent-runs",
    response_model=AgentRunState,
    status_code=status.HTTP_201_CREATED,
)
async def start_agent_run_for_session(
    session_id: str,
    request: SessionAgentRunRequest,
    interface: InterfaceDependency,
) -> AgentRunState:
    return await interface.sessions.start_agent_run_for_session(session_id, request)


@router.put("/{session_id}", response_model=Session)
async def replace_session(
    session_id: str,
    session: Session,
    interface: InterfaceDependency,
) -> Session:
    updated = (
        session
        if session.session_id == session_id
        else session.model_copy(update={"session_id": session_id})
    )
    return await interface.sessions.replace_session(updated)


@router.post("/{session_id}/archive", response_model=Session)
async def archive_session(
    session_id: str,
    interface: InterfaceDependency,
) -> Session:
    return await interface.sessions.archive_session(session_id)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_session(
    session_id: str,
    interface: InterfaceDependency,
) -> None:
    await interface.sessions.delete_session(session_id)
