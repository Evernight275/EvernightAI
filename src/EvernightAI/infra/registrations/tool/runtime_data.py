from EvernightAI.core.protocol.context import ContextManageProtocol
from EvernightAI.core.protocol.memory import MemoryManageProtocol
from EvernightAI.core.protocol.tool import ToolRegisterProtocol
from EvernightAI.infra.adapters.tool.runtime_data import (
    AppendContextMessageTool,
    CreateContextTool,
    WriteMemoryTool,
)


def register_runtime_data_tools(
    register: ToolRegisterProtocol,
    *,
    contexts: ContextManageProtocol,
    memories: MemoryManageProtocol,
) -> None:
    tools = [
        CreateContextTool(contexts),
        AppendContextMessageTool(contexts),
        WriteMemoryTool(memories),
    ]
    for tool in tools:
        register.register(tool.definition, tool.executor())
