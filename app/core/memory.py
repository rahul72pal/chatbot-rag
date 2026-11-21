"""Consented user preference persistence and prompt retrieval."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserMemory

MAX_USER_MEMORY_ITEMS = 50


async def list_user_memory(db: AsyncSession, user: User) -> list[UserMemory]:
    if not user.memory_consent:
        return []
    stmt = (
        select(UserMemory)
        .where(UserMemory.user_id == user.id)
        .order_by(UserMemory.id.desc())
        .limit(MAX_USER_MEMORY_ITEMS)
    )
    return list((await db.scalars(stmt)).all())
