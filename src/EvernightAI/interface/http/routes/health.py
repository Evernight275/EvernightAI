from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Health check",
    operation_id="health",
)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Readiness check",
    operation_id="ready",
)
async def ready(request: Request) -> dict[str, str]:
    readiness_checker = cast(
        Callable[[], bool],
        request.app.state.readiness_checker,
    )
    if not readiness_checker():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime initialization or database readiness check failed",
        )
    return {"status": "ready"}
