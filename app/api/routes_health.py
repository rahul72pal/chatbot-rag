from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["System"])


@router.api_route("/health", methods=["GET", "HEAD"], summary="Health check")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"status": "healthy", "app_name": settings.APP_NAME}
