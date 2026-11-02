from EvernightAI.core.protocol.shell import ShellSessionStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.shell import ShellSessionState


class ShellSessionStore(ShellSessionStoreProtocol):
    def __init__(self) -> None:
        self._states: dict[tuple[str | None, str], ShellSessionState] = {}

    def get(
        self, session_key: str, *, principal_scope: PrincipalScope | None = None
    ) -> ShellSessionState | None:
        state = self._states.get((_owner(principal_scope), session_key))
        return state.model_copy(deep=True) if state is not None else None

    def save(
        self,
        state: ShellSessionState,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self._states[(_owner(principal_scope), state.session_key)] = state.model_copy(
            deep=True
        )

    def delete(
        self, session_key: str, *, principal_scope: PrincipalScope | None = None
    ) -> None:
        self._states.pop((_owner(principal_scope), session_key), None)


def _owner(scope: PrincipalScope | None) -> str | None:
    return scope.owner_id if scope else None
