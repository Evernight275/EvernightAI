from EvernightAI.application.agent import AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.core.protocol.interface import SessionInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.error.session import SessionInputError
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunState
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
    SessionChatResult,
    SessionStatus,
)


class SessionApplication(SessionInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def create_session(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        await self._ensure_context(session, principal_scope=principal_scope)
        return await self._runtime.sessions.create(
            session,
            principal_scope=principal_scope,
        )

    async def get_session(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        return await self._runtime.sessions.get(
            session_id,
            principal_scope=principal_scope,
        )

    async def replace_session(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        await self._runtime.sessions.get(
            session.session_id,
            principal_scope=principal_scope,
        )
        await self._ensure_context(session, principal_scope=principal_scope)
        return await self._runtime.sessions.replace(
            session,
            principal_scope=principal_scope,
        )

    async def archive_session(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        return await self._runtime.sessions.archive(
            session_id,
            principal_scope=principal_scope,
        )

    async def list_sessions(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        owner_id: str | None = None,
        status: SessionStatus | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        principal_scope: PrincipalScope | None = None,
    ) -> list[Session]:
        return await self._runtime.sessions.list_sessions(
            cursor=cursor,
            limit=limit,
            owner_id=owner_id,
            status=status,
            provider_id=provider_id,
            model_id=model_id,
            principal_scope=principal_scope,
        )

    async def delete_session(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        await self._runtime.sessions.delete(
            session_id,
            principal_scope=principal_scope,
        )

    async def chat_with_session(
        self,
        session_id: str,
        request: SessionChatRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> SessionChatResult:
        session = await self._runtime.sessions.get(
            session_id,
            principal_scope=principal_scope,
        )
        response = await ChatApplication(self._runtime).chat_with_context(
            self._required_provider_id(session, request),
            session.context_id,
            model_id=self._required_model_id(session, request),
            messages=request.messages,
            retry_from_message_index=request.retry_from_message_index,
            memory_query=request.memory_query,
            skills=request.skills,
            tools=request.tools,
            metadata=self._session_metadata(session, request.metadata),
            principal_scope=principal_scope,
        )

        return SessionChatResult(session=session, response=response)

    async def start_agent_run_for_session(
        self,
        session_id: str,
        request: SessionAgentRunRequest,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> AgentRunState:
        session = await self._runtime.sessions.get(
            session_id,
            principal_scope=principal_scope,
        )
        agent_request = AgentRunRequest(
            provider_id=self._required_provider_id(session, request),
            owner_id=session.owner_id,
            context_id=session.context_id,
            model_id=self._required_model_id(session, request),
            messages=request.messages,
            retry_from_message_index=request.retry_from_message_index,
            memory_query=request.memory_query,
            skills=request.skills,
            tools=request.tools,
            max_tool_rounds=request.max_tool_rounds,
            recover_tool_errors=request.recover_tool_errors,
            write_memory=request.write_memory,
            tool_approvals=request.tool_approvals,
            pause_on_approval=request.pause_on_approval,
            timeout_seconds=request.timeout_seconds,
            metadata=self._session_metadata(session, request.metadata),
        )

        return await AgentRunApplication(self._runtime).start(
            agent_request,
            principal_scope=principal_scope,
        )

    async def _ensure_context(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        if self._runtime.context_register.has(
            session.context_id,
            principal_scope=principal_scope,
        ):
            return

        await self._runtime.contexts.create(
            Context(
                context_id=session.context_id,
                owner_id=session.owner_id,
                metadata={"session_id": session.session_id},
            ),
            principal_scope=principal_scope,
        )

    def _required_provider_id(
        self,
        session: Session,
        request: SessionChatRequest | None = None,
    ) -> str:
        if request is not None and request.provider_id:
            return request.provider_id
        if session.provider_id:
            return session.provider_id

        raise SessionInputError("Session provider_id is required")

    def _required_model_id(
        self,
        session: Session,
        request: SessionChatRequest | None = None,
    ) -> str:
        if request is not None and request.model_id:
            return request.model_id
        if session.model_id:
            return session.model_id

        raise SessionInputError("Session model_id is required")

    def _session_metadata(
        self,
        session: Session,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        return {
            **metadata,
            "session_id": session.session_id,
        }
