from typing import Protocol

from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.shell import ShellSessionState


class ShellSessionStoreProtocol(Protocol):
    """
    Shell会话状态存储协议
    """

    def get(
        self, session_key: str, *, principal_scope: PrincipalScope | None = None
    ) -> ShellSessionState | None: ...

    def save(
        self,
        state: ShellSessionState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None: ...

    def delete(
        self, session_key: str, *, principal_scope: PrincipalScope | None = None
    ) -> None: ...
