from EvernightAI.application.agent import AgentRunApplication
from EvernightAI.application.chat import ChatApplication
from EvernightAI.core.protocol.interface import SessionInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.error.session import SessionInputError
from EvernightAI.core.schema.agent import AgentRunRequest, AgentRunState
from EvernightAI.core.schema.context import Context
from EvernightAI.core.schema.session import (
    Session,
    SessionAgentRunRequest,
    SessionChatRequest,
    SessionChatResult,
)


class SessionApplication(SessionInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    async def create_session(self, session: Session) -> Session:
        await self._ensure_context(session)
        return await self._runtime.sessions.create(session)

    async def get_session(self, session_id: str) -> Session:
        return await self._runtime.sessions.get(session_id)

    async def replace_session(self, session: Session) -> Session:
        await self._runtime.sessions.get(session.session_id)
        await self._ensure_context(session)
        return await self._runtime.sessions.replace(session)

    async def archive_session(self, session_id: str) -> Session:
        return await self._runtime.sessions.archive(session_id)

    async def list_sessions(self) -> list[Session]:
        return await self._runtime.sessions.list_sessions()

    async def delete_session(self, session_id: str) -> None:
        await self._runtime.sessions.delete(session_id)

    async def chat_with_session(
        self,
        session_id: str,
        request: SessionChatRequest,
    ) -> SessionChatResult:
        session = await self._runtime.sessions.get(session_id)
        response = await ChatApplication(self._runtime).chat_with_context(
            self._required_provider_id(session),
            session.context_id,
            model_id=self._required_model_id(session),
            messages=request.messages,
            memory_query=request.memory_query,
            skills=request.skills,
            tools=request.tools,
            metadata=self._session_metadata(session, request.metadata),
        )

        return SessionChatResult(session=session, response=response)

    async def start_agent_run_for_session(
        self,
        session_id: str,
        request: SessionAgentRunRequest,
    ) -> AgentRunState:
        session = await self._runtime.sessions.get(session_id)
        agent_request = AgentRunRequest(
            provider_id=self._required_provider_id(session),
            context_id=session.context_id,
            model_id=self._required_model_id(session),
            messages=request.messages,
            memory_query=request.memory_query,
            skills=request.skills,
            tools=request.tools,
            max_tool_rounds=request.max_tool_rounds,
            recover_tool_errors=request.recover_tool_errors,
            write_memory=request.write_memory,
            tool_approvals=request.tool_approvals,
            pause_on_approval=request.pause_on_approval,
            metadata=self._session_metadata(session, request.metadata),
        )

        return await AgentRunApplication(self._runtime).start(agent_request)

    async def _ensure_context(self, session: Session) -> None:
        if self._runtime.context_register.has(session.context_id):
            return

        await self._runtime.contexts.create(
            Context(
                context_id=session.context_id,
                metadata={"session_id": session.session_id},
            )
        )

    def _required_provider_id(self, session: Session) -> str:
        if session.provider_id:
            return session.provider_id

        raise SessionInputError("Session provider_id is required")

    def _required_model_id(self, session: Session) -> str:
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
