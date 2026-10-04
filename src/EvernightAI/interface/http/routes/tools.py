from fastapi import APIRouter, Response

from EvernightAI.core.schema.tool import (
    ToolDefinition,
    ToolPolicySummary,
    ToolPolicyUpdate,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency


router = APIRouter(prefix="/tools", tags=["tools"])


@router.get(
    "",
    response_model=list[ToolDefinition],
    response_model_exclude_none=True,
    summary="List available tools",
    operation_id="list_tools",
)
async def list_tools(
    interface: InterfaceDependency, response: Response
) -> list[ToolDefinition]:
    response.headers["Cache-Control"] = "no-store"
    return interface.tools.list_tools()


@router.get(
    "/policies",
    response_model=list[ToolPolicySummary],
    summary="List current user's tool policies",
    operation_id="list_tool_policies",
)
async def list_tool_policies(
    interface: InterfaceDependency, response: Response
) -> list[ToolPolicySummary]:
    response.headers["Cache-Control"] = "no-store"
    return interface.tools.list_tool_policies()


@router.put(
    "/{tool_name}/policy",
    response_model=ToolPolicySummary,
    summary="Set current user's tool policy",
    operation_id="set_tool_policy",
)
async def set_tool_policy(
    tool_name: str,
    update: ToolPolicyUpdate,
    interface: InterfaceDependency,
    response: Response,
) -> ToolPolicySummary:
    response.headers["Cache-Control"] = "no-store"
    return interface.tools.set_tool_policy(tool_name, update.mode)


@router.delete(
    "/{tool_name}/policy",
    response_model=ToolPolicySummary,
    summary="Restore the default tool policy",
    operation_id="reset_tool_policy",
)
async def reset_tool_policy(
    tool_name: str, interface: InterfaceDependency, response: Response
) -> ToolPolicySummary:
    response.headers["Cache-Control"] = "no-store"
    return interface.tools.set_tool_policy(tool_name, None)
