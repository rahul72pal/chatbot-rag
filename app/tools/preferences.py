"""Explicit, consent-gated user preference memory tool."""

from __future__ import annotations

import hashlib
import json

from langchain_core.tools import tool
from sqlalchemy import func, select

from app.core.context import current_user_id, current_voice_session_id
from app.core.memory import MAX_USER_MEMORY_ITEMS
from app.db.database import SessionLocal
from app.db.models import ToolExecution, UserMemory


@tool
async def save_preference(key: str, value: str) -> str:
    """Save a user preference only when the user explicitly asks you to remember it.

    Never use this tool to store facts inferred from the conversation. Memory must
    be enabled by the user. Examples include a preferred language or speaking style.
    """
    user_id = current_user_id.get()
    session_id = current_voice_session_id.get()
    normalized_key = (key or "").strip().lower()
    normalized_value = (value or "").strip()
    if not user_id or not session_id:
        return json.dumps({"ok": False, "error": "voice_session_context_missing"})
    if not normalized_key or len(normalized_key) > 64 or not normalized_value:
        return json.dumps({"ok": False, "error": "invalid_preference"})
    if len(normalized_value) > 500:
        return json.dumps({"ok": False, "error": "preference_too_long"})

    idempotency_key = hashlib.sha256(
        f"{user_id}:{session_id}:save_preference:{normalized_key}:{normalized_value}".encode("utf-8")
    ).hexdigest()

    async with SessionLocal.begin() as db:
        execution = await db.scalar(
            select(ToolExecution).where(ToolExecution.idempotency_key == idempotency_key)
        )
        if execution:
            return json.dumps(execution.result)

        from app.db.models import User

        user = await db.get(User, user_id)
        if user is None or not user.memory_consent:
            result = {"ok": False, "error": "memory_consent_required"}
        else:
            memory = await db.scalar(
                select(UserMemory).where(
                    UserMemory.user_id == user_id,
                    UserMemory.key == normalized_key,
                )
            )
            if memory is None:
                memory = UserMemory(user_id=user_id, key=normalized_key, value=normalized_value)
                db.add(memory)
            else:
                memory.value = normalized_value

            await db.flush()
            total = await db.scalar(
                select(func.count(UserMemory.id)).where(UserMemory.user_id == user_id)
            )
            if int(total or 0) > MAX_USER_MEMORY_ITEMS:
                oldest = list((await db.scalars(
                    select(UserMemory)
                    .where(UserMemory.user_id == user_id, UserMemory.id != memory.id)
                    .order_by(UserMemory.id)
                    .limit(int(total or 0) - MAX_USER_MEMORY_ITEMS)
                )).all())
                for item in oldest:
                    await db.delete(item)

            result = {"ok": True, "saved": normalized_key}

        # Cache successful writes only. A declined write must be retryable after
        # the user enables consent in this same session.
        if result.get("ok"):
            db.add(ToolExecution(
                idempotency_key=idempotency_key,
                session_id=session_id,
                tool="save_preference",
                args={"key": normalized_key},
                result=result,
            ))
    return json.dumps(result)
