from fastapi import APIRouter

from EvernightAI.core.schema.tool import ToolDefinition
from EvernightAI.interface.http.dependencies import InterfaceDependency


router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolDefinition])
async def list_tools(interface: InterfaceDependency) -> list[ToolDefinition]:
    return interface.runtime.tools.list_tools()
