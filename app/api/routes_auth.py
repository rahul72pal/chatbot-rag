"""API-prefixed alias for the existing authentication routes."""

from app.routes.auth import router

__all__ = ["router"]
