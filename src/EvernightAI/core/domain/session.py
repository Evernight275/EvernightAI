from EvernightAI.core.error.session import SessionNotFoundError
from EvernightAI.core.protocol.session import (
    SessionManageProtocol,
    SessionRegisterProtocol,
)
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.session import Session, SessionStatus, utc_now


def _scope_permits(
    principal_scope: PrincipalScope | None,
    owner_id: str | None,
) -> bool:
    return principal_scope is None or principal_scope.permits(owner_id)


def _require_session_scope(
    session: Session,
    principal_scope: PrincipalScope | None,
) -> None:
    if not _scope_permits(principal_scope, session.owner_id):
        raise SessionNotFoundError(
            f"The session {session.session_id} is not available in this scope"
        )


class SessionRegister(SessionRegisterProtocol):
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def register(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注册会话"""
        _require_session_scope(session, principal_scope)
        self._sessions[session.session_id] = session

    def unregister(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """注销会话"""
        if not self.has(session_id, principal_scope=principal_scope):
            raise SessionNotFoundError(f"The session {session_id} is not registered")

        self._sessions.pop(session_id, None)

    def get(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        """获取会话"""
        if self.has(session_id, principal_scope=principal_scope):
            return self._sessions[session_id]

        raise SessionNotFoundError(f"The session {session_id} is not found")

    def has(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> bool:
        """检查会话是否存在"""
        session = self._sessions.get(session_id)
        return session is not None and _scope_permits(principal_scope, session.owner_id)

    def list_sessions(
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
        """列出所有会话"""
        sessions = sorted(self._sessions.values(), key=lambda item: item.session_id)
        if cursor is not None:
            sessions = [item for item in sessions if item.session_id > cursor]
        if principal_scope is not None and principal_scope.owner_id is not None:
            if owner_id is not None and owner_id != principal_scope.owner_id:
                return []
            owner_id = principal_scope.owner_id
        if owner_id is not None:
            sessions = [item for item in sessions if item.owner_id == owner_id]
        if status is not None:
            sessions = [item for item in sessions if item.status is status]
        if provider_id is not None:
            sessions = [item for item in sessions if item.provider_id == provider_id]
        if model_id is not None:
            sessions = [item for item in sessions if item.model_id == model_id]
        return sessions if limit is None else sessions[:limit]


class SessionManager(SessionManageProtocol):
    def __init__(self, register: SessionRegisterProtocol) -> None:
        self._register = register

    async def create(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        """创建会话"""
        self._register.register(session, principal_scope=principal_scope)
        return self._register.get(
            session.session_id,
            principal_scope=principal_scope,
        )

    async def get(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        """获取会话"""
        return self._register.get(session_id, principal_scope=principal_scope)

    async def replace(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        """替换会话"""
        if not self._register.has(
            session.session_id,
            principal_scope=principal_scope,
        ):
            raise SessionNotFoundError(f"The session {session.session_id} is not found")

        updated = session.model_copy(update={"updated_at": utc_now()})
        self._register.register(updated, principal_scope=principal_scope)
        return self._register.get(
            session.session_id,
            principal_scope=principal_scope,
        )

    async def archive(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session:
        """归档会话"""
        session = self._register.get(session_id, principal_scope=principal_scope)
        updated = session.model_copy(
            update={
                "status": SessionStatus.ARCHIVED,
                "updated_at": utc_now(),
            }
        )
        self._register.register(updated, principal_scope=principal_scope)
        return updated

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
        """列出所有会话"""
        return self._register.list_sessions(
            cursor=cursor,
            limit=limit,
            owner_id=owner_id,
            status=status,
            provider_id=provider_id,
            model_id=model_id,
            principal_scope=principal_scope,
        )

    async def delete(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """删除会话"""
        self._register.unregister(session_id, principal_scope=principal_scope)

    async def clear(
        self,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        """清空会话"""
        for session in list(
            self._register.list_sessions(principal_scope=principal_scope)
        ):
            self._register.unregister(
                session.session_id,
                principal_scope=principal_scope,
            )
