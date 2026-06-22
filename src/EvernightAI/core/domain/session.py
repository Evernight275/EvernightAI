from EvernightAI.core.error.session import SessionNotFoundError
from EvernightAI.core.protocol.session import (
    SessionManageProtocol,
    SessionRegisterProtocol,
)
from EvernightAI.core.schema.session import Session, SessionStatus, utc_now


class SessionRegister(SessionRegisterProtocol):
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def register(self, session: Session) -> None:
        """注册会话"""
        self._sessions[session.session_id] = session

    def unregister(self, session_id: str) -> None:
        """注销会话"""
        if not self.has(session_id):
            raise SessionNotFoundError(f"The session {session_id} is not registered")

        self._sessions.pop(session_id, None)

    def get(self, session_id: str) -> Session:
        """获取会话"""
        if self.has(session_id):
            return self._sessions[session_id]

        raise SessionNotFoundError(f"The session {session_id} is not found")

    def has(self, session_id: str) -> bool:
        """检查会话是否存在"""
        return session_id in self._sessions

    def list_sessions(self) -> list[Session]:
        """列出所有会话"""
        return list(self._sessions.values())


class SessionManager(SessionManageProtocol):
    def __init__(self, register: SessionRegisterProtocol) -> None:
        self._register = register

    async def create(self, session: Session) -> Session:
        """创建会话"""
        self._register.register(session)
        return self._register.get(session.session_id)

    async def get(self, session_id: str) -> Session:
        """获取会话"""
        return self._register.get(session_id)

    async def replace(self, session: Session) -> Session:
        """替换会话"""
        if not self._register.has(session.session_id):
            raise SessionNotFoundError(f"The session {session.session_id} is not found")

        updated = session.model_copy(update={"updated_at": utc_now()})
        self._register.register(updated)
        return self._register.get(session.session_id)

    async def archive(self, session_id: str) -> Session:
        """归档会话"""
        session = self._register.get(session_id)
        updated = session.model_copy(
            update={
                "status": SessionStatus.ARCHIVED,
                "updated_at": utc_now(),
            }
        )
        self._register.register(updated)
        return updated

    async def list_sessions(self) -> list[Session]:
        """列出所有会话"""
        return self._register.list_sessions()

    async def delete(self, session_id: str) -> None:
        """删除会话"""
        self._register.unregister(session_id)

    async def clear(self) -> None:
        """清空会话"""
        for session in list(self._register.list_sessions()):
            self._register.unregister(session.session_id)
