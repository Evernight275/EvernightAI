from EvernightAI.core.protocol.base import (
    EvernightAIProtocol,
    ManageProtocol,
    RegisterProtocol,
)
from EvernightAI.core.schema.session import Session


class SessionProtocol(EvernightAIProtocol):
    """
    会话协议
    """

    ...


class SessionRegisterProtocol(SessionProtocol, RegisterProtocol):
    """
    会话注册协议
    """

    def register(self, session: Session) -> None: ...

    def unregister(self, session_id: str) -> None: ...

    def get(self, session_id: str) -> Session: ...

    def has(self, session_id: str) -> bool: ...

    def list_sessions(self) -> list[Session]: ...


class SessionManageProtocol(SessionProtocol, ManageProtocol):
    """
    会话管理协议
    """

    async def create(self, session: Session) -> Session: ...

    async def get(self, session_id: str) -> Session: ...

    async def replace(self, session: Session) -> Session: ...

    async def archive(self, session_id: str) -> Session: ...

    async def list_sessions(self) -> list[Session]: ...

    async def delete(self, session_id: str) -> None: ...

    async def clear(self) -> None: ...
