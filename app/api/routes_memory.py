"""User-controlled consent and long-term preference memory routes."""

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.memory import list_user_memory
from app.core.session import ensure_voice_user
from app.db.database import get_db
from app.db.models import ConversationSession, ToolExecution, UserMemory

router = APIRouter(prefix="/voice/memory", tags=["Voice Memory"])


class MemoryConsentUpdate(BaseModel):
    memory_consent: bool


@router.get("/consent")
async def get_memory_consent(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    user = await ensure_voice_user(db, str(current_user["id"]), current_user.get("email"))
    await db.commit()
    return {"memory_consent": user.memory_consent}


@router.put("/consent")
async def set_memory_consent(
    payload: MemoryConsentUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool | int]:
    user = await ensure_voice_user(db, str(current_user["id"]), current_user.get("email"))
    user.memory_consent = payload.memory_consent
    deleted_count = 0
    if not payload.memory_consent:
        result = await db.execute(delete(UserMemory).where(UserMemory.user_id == user.id))
        deleted_count = int(result.rowcount or 0)
        user_sessions = select(ConversationSession.id).where(ConversationSession.user_id == user.id)
        await db.execute(
            delete(ToolExecution)
            .where(ToolExecution.session_id.in_(user_sessions))
            .where(ToolExecution.tool == "save_preference")
        )
    await db.commit()
    return {"memory_consent": user.memory_consent, "deleted_memory_items": deleted_count}


@router.get("")
async def list_memory(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await ensure_voice_user(db, str(current_user["id"]), current_user.get("email"))
    items = await list_user_memory(db, user)
    await db.commit()
    return {
        "memory_consent": user.memory_consent,
        "retention_limit": 50,
        "items": [{"id": item.id, "key": item.key, "value": item.value} for item in items],
    }


@router.delete("")
async def delete_all_memory(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    user_id = str(current_user["id"])
    await ensure_voice_user(db, user_id, current_user.get("email"))
    result = await db.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
    deleted_count = int(result.rowcount or 0)
    user_sessions = select(ConversationSession.id).where(ConversationSession.user_id == user_id)
    await db.execute(
        delete(ToolExecution)
        .where(ToolExecution.session_id.in_(user_sessions))
        .where(ToolExecution.tool == "save_preference")
    )
    await db.commit()
    return {"deleted_memory_items": deleted_count}


@router.delete("/{memory_id}")
async def delete_memory_item(
    memory_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    result = await db.execute(
        delete(UserMemory).where(
            UserMemory.id == memory_id,
            UserMemory.user_id == str(current_user["id"]),
        )
    )
    await db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory item not found.")
    return {"deleted_memory_items": 1}
