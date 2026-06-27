from EvernightAI.core.protocol.context import ContextManageProtocol
from EvernightAI.core.protocol.memory import MemoryManageProtocol
from EvernightAI.core.protocol.session import SessionManageProtocol
from EvernightAI.core.protocol.tool import ToolRegisterProtocol
from EvernightAI.infra.adapters.tool.runtime_data import (
    AppendContextMessageTool,
    ArchiveSessionTool,
    CreateContextTool,
    CreateSessionTool,
    GetContextTool,
    GetMemoryTool,
    GetSessionTool,
    ListContextsTool,
    ListMemoriesTool,
    ListSessionsTool,
    WriteMemoryTool,
)


def register_runtime_data_tools(
    register: ToolRegisterProtocol,
    *,
    contexts: ContextManageProtocol,
    memories: MemoryManageProtocol,
    sessions: SessionManageProtocol,
) -> None:
    tools = [
        CreateContextTool(contexts),
        ListContextsTool(contexts),
        GetContextTool(contexts),
        AppendContextMessageTool(contexts),
        WriteMemoryTool(memories),
        ListMemoriesTool(memories),
        GetMemoryTool(memories),
        CreateSessionTool(sessions),
        ListSessionsTool(sessions),
        GetSessionTool(sessions),
        ArchiveSessionTool(sessions),
    ]
    for tool in tools:
        register.register(tool.definition, tool.executor())
