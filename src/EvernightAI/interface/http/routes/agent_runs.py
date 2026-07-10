from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Body, Query, status
from fastapi.responses import StreamingResponse

from EvernightAI.core.protocol.stream import AgentTraceStreamProtocol
from EvernightAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunState,
    AgentRunStatus,
    AgentTraceEvent,
)
from EvernightAI.core.schema.stream import SSEEvent
from EvernightAI.core.schema.tool import ToolApprovalDecision, ToolApprovalStatus
from EvernightAI.interface.http.dependencies import InterfaceDependency
from EvernightAI.interface.http.schema import ResumeAgentRunRequest
from EvernightAI.interface.http.template import (
    AGENT_RUN_STATE_RESPONSE_EXAMPLE,
    AGENT_TRACE_SSE_EXAMPLE,
    AGENT_RUN_EXAMPLES,
    RESUME_AGENT_RUN_EXAMPLES,
)
from EvernightAI.interface.http.sse import sse_response_body


router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


@router.post(
    "",
    response_model=AgentRunState,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="Start an agent run",
    description=(
        "Run a model against a context, optionally allowing tool rounds. Set "
        "`max_tool_rounds` to 0 for a single plain chat step."
    ),
    operation_id="start_agent_run",
    responses={201: AGENT_RUN_STATE_RESPONSE_EXAMPLE},
)
async def start_agent_run(
    request: Annotated[
        AgentRunRequest,
        Body(openapi_examples=AGENT_RUN_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> AgentRunState:
    return await interface.agent_runs.start(request)


@router.post(
    "/stream",
    summary="Stream an agent run",
    description="SSE transport for a new agent run trace.",
    operation_id="stream_agent_run",
    responses={200: AGENT_TRACE_SSE_EXAMPLE},
)
async def stream_agent_run(
    request: Annotated[
        AgentRunRequest,
        Body(openapi_examples=AGENT_RUN_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> StreamingResponse:
    stream = interface.agent_runs.start_stream(request)
    return StreamingResponse(
        sse_response_body(_agent_trace_sse_events(stream)),
        media_type="text/event-stream",
    )


@router.get(
    "",
    response_model=list[AgentRunState],
    response_model_exclude_none=True,
    summary="List agent run states",
    operation_id="list_agent_runs",
)
async def list_agent_runs(
    interface: InterfaceDependency,
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    owner_id: str | None = Query(default=None),
    status_filter: AgentRunStatus | None = Query(default=None, alias="status"),
    context_id: str | None = Query(default=None),
) -> list[AgentRunState]:
    return interface.agent_runs.list_states(
        cursor=cursor,
        limit=limit,
        owner_id=owner_id,
        status=status_filter,
        context_id=context_id,
    )


@router.get(
    "/{run_id}",
    response_model=AgentRunState,
    response_model_exclude_none=True,
    summary="Get an agent run state",
    operation_id="get_agent_run",
)
async def get_agent_run(
    run_id: str,
    interface: InterfaceDependency,
) -> AgentRunState:
    return interface.agent_runs.get_state(run_id)


@router.post(
    "/{run_id}/resume",
    response_model=AgentRunState,
    response_model_exclude_none=True,
    summary="Resume a paused agent run",
    description="Supply approval decisions for pending tool calls, then continue the run.",
    operation_id="resume_agent_run",
    responses={200: AGENT_RUN_STATE_RESPONSE_EXAMPLE},
)
async def resume_agent_run(
    run_id: str,
    request: Annotated[
        ResumeAgentRunRequest,
        Body(openapi_examples=RESUME_AGENT_RUN_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> AgentRunState:
    return await interface.agent_runs.resume(run_id, request.approvals)


@router.post(
    "/{run_id}/approve-pending",
    response_model=AgentRunState,
    response_model_exclude_none=True,
    summary="Approve all pending tool calls",
    description="Convenience endpoint for approving every pending tool approval request.",
    operation_id="approve_pending_agent_run",
    responses={200: AGENT_RUN_STATE_RESPONSE_EXAMPLE},
)
async def approve_pending_agent_run(
    run_id: str,
    interface: InterfaceDependency,
) -> AgentRunState:
    state = interface.agent_runs.get_state(run_id)
    return await interface.agent_runs.resume(
        run_id,
        _approve_pending_tool_calls(state),
    )


@router.post(
    "/{run_id}/resume/stream",
    summary="Stream resume of a paused agent run",
    description="SSE transport for resuming a paused run after approval decisions.",
    operation_id="resume_agent_run_stream",
    responses={200: AGENT_TRACE_SSE_EXAMPLE},
)
async def resume_agent_run_stream(
    run_id: str,
    request: Annotated[
        ResumeAgentRunRequest,
        Body(openapi_examples=RESUME_AGENT_RUN_EXAMPLES),
    ],
    interface: InterfaceDependency,
) -> StreamingResponse:
    stream = interface.agent_runs.resume_stream(run_id, request.approvals)
    return StreamingResponse(
        sse_response_body(_agent_trace_sse_events(stream)),
        media_type="text/event-stream",
    )


@router.get(
    "/{run_id}/trace",
    response_model=list[AgentTraceEvent],
    response_model_exclude_none=True,
    summary="List agent trace events",
    operation_id="list_agent_trace",
)
async def list_agent_trace(
    run_id: str,
    interface: InterfaceDependency,
    after_sequence: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=1000),
) -> list[AgentTraceEvent]:
    return interface.agent_runs.list_trace(
        run_id,
        after_sequence=after_sequence,
        limit=limit,
    )


async def _agent_trace_sse_events(
    stream: AgentTraceStreamProtocol,
) -> AsyncIterator[SSEEvent]:
    async for event in stream:
        yield SSEEvent(
            data=event.model_dump_json(exclude_none=True),
            event=event.event_type.value,
        )


def _approve_pending_tool_calls(
    state: AgentRunState,
) -> list[ToolApprovalDecision]:
    return [
        ToolApprovalDecision(
            approval_id=request.approval_id,
            tool_call_id=request.tool_call_id,
            status=ToolApprovalStatus.APPROVED,
        )
        for request in state.pending_approval_requests
    ]
