from fastapi import APIRouter

from EvernightAI.core.schema.tool import ToolDefinition
from EvernightAI.interface.http.dependencies import InterfaceDependency


router = APIRouter(prefix="/tools", tags=["tools"])


@router.get(
    "",
    response_model=list[ToolDefinition],
    response_model_exclude_none=True,
    summary="List tools",
    description="Return tools registered in the runtime, such as restricted filesystem or shell tools.",
    operation_id="list_tools",
)
async def list_tools(interface: InterfaceDependency) -> list[ToolDefinition]:
    return interface.tools.list_tools()
