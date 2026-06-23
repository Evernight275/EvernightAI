from EvernightAI.core.protocol.interface import ToolInterfaceProtocol
from EvernightAI.core.protocol.runtime import RuntimeProtocol
from EvernightAI.core.schema.tool import ToolDefinition


class ToolApplication(ToolInterfaceProtocol):
    def __init__(self, runtime: RuntimeProtocol) -> None:
        self._runtime = runtime

    def list_tools(self) -> list[ToolDefinition]:
        return self._runtime.tools.list_tools()
