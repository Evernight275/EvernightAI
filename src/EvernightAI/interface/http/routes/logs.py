from typing import Annotated

from fastapi import APIRouter, Query, status

from EvernightAI.interface.log_store import RECENT_LOG_STORE, LogEntry


router = APIRouter(prefix="/logs", tags=["logs"])


@router.get(
    "",
    response_model=list[LogEntry],
    response_model_exclude_none=True,
    summary="List recent process logs",
    description="Return recent in-memory process logs captured by the local logging handler.",
    operation_id="list_recent_logs",
)
async def list_recent_logs(
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    after: Annotated[int | None, Query(ge=0)] = None,
) -> list[LogEntry]:
    return RECENT_LOG_STORE.list(limit=limit, after=after)


@router.post(
    "/clear",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear recent process logs",
    description="Clear the in-memory log buffer for the current process.",
    operation_id="clear_recent_logs",
)
async def clear_recent_logs() -> None:
    RECENT_LOG_STORE.clear()
