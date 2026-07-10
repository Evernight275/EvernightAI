from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    ManageProtocol,
    RegisterProtocol,
)
from EvernightAI.core.schema.session import Session, SessionStatus
from EvernightAI.core.schema.auth import PrincipalScope


class SessionProtocol(EvernightAIProtocol):
    """
    会话协议
    """

    ...


class SessionRegisterProtocol(SessionProtocol, RegisterProtocol):
    """
    会话注册协议
    """

    def register(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    def unregister(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    def get(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session: ...

    def has(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> bool: ...

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
    ) -> list[Session]: ...


class SessionManageProtocol(SessionProtocol, ManageProtocol):
    """
    会话管理协议
    """

    async def create(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session: ...

    async def get(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session: ...

    async def replace(
        self,
        session: Session,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session: ...

    async def archive(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> Session: ...

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
    ) -> list[Session]: ...

    async def delete(
        self,
        session_id: str,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    async def clear(
        self,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...
