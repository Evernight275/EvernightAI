from fastapi import APIRouter, status

from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentTraceEvent,
)
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.schema import ResumeAgentRunRequest


router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


@router.post(
    "",
    response_model=AgentRunState,
    status_code=status.HTTP_201_CREATED,
)
async def start_agent_run(
    request: AgentRunRequest,
    interface: InterfaceDependency,
) -> AgentRunState:
    return await interface.agent_runs.start(request)


@router.get("", response_model=list[AgentRunState])
async def list_agent_runs(interface: InterfaceDependency) -> list[AgentRunState]:
    return interface.agent_runs.list_states()


@router.get("/{run_id}", response_model=AgentRunState)
async def get_agent_run(
    run_id: str,
    interface: InterfaceDependency,
) -> AgentRunState:
    return interface.agent_runs.get_state(run_id)


@router.post("/{run_id}/resume", response_model=AgentRunState)
async def resume_agent_run(
    run_id: str,
    request: ResumeAgentRunRequest,
    interface: InterfaceDependency,
) -> AgentRunState:
    return await interface.agent_runs.resume(run_id, request.approvals)


@router.get("/{run_id}/trace", response_model=list[AgentTraceEvent])
async def list_agent_trace(
    run_id: str,
    interface: InterfaceDependency,
) -> list[AgentTraceEvent]:
    return interface.agent_runs.list_trace(run_id)
