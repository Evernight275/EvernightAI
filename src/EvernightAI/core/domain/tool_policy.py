from EvernightAI.core.protocol.tool import ToolPolicyStoreProtocol
from EvernightAI.core.schema.auth import PrincipalScope
from EvernightAI.core.schema.tool import ToolAccessMode


class ToolPolicyStore(ToolPolicyStoreProtocol):
    def __init__(self) -> None:
        self._policies: dict[tuple[str | None, str], ToolAccessMode] = {}

    def get(
        self, tool_name: str, *, principal_scope: PrincipalScope | None = None
    ) -> ToolAccessMode | None:
        return self._policies.get(
            (principal_scope.owner_id if principal_scope else None, tool_name)
        )

    def set(
        self,
        tool_name: str,
        mode: ToolAccessMode,
        *,
        principal_scope: PrincipalScope | None = None,
    ) -> None:
        self._policies[
            (principal_scope.owner_id if principal_scope else None, tool_name)
        ] = mode

    def delete(
        self, tool_name: str, *, principal_scope: PrincipalScope | None = None
    ) -> None:
        self._policies.pop(
            (principal_scope.owner_id if principal_scope else None, tool_name), None
        )
