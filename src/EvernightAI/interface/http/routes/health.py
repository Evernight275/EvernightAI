from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Health check",
    operation_id="health",
)
async def health() -> dict[str, str]:
    return {"status": "ok"}
