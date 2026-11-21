"""Public voice session lifecycle.

The voice agent is open to any visitor, so there is no login. A caller asks
for a session, gets an opaque id, and sends that id with each audio turn.
Identity is generated server-side and is never accepted from the client.
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.session import (
    create_public_session,
    get_session,
    purge_expired_public_sessions,
)
from app.db.database import get_db
from app.db.models import Message, PendingConfirmation, ToolExecution, User

router = APIRouter(prefix="/voice", tags=["Voice Session"])

WINDOW_SECONDS = 3600
_creation_log: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = asyncio.Lock()
_last_purge = 0.0


class SessionCreateRequest(BaseModel):
    language: str | None = Field(default=None, max_length=10)


class SessionCreated(BaseModel):
    session_id: str
    language: str | None
    expires_in_hours: int


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _check_rate_limit(ip: str) -> None:
    limit = settings.PUBLIC_SESSION_MAX_PER_IP_PER_HOUR
    if limit <= 0:
        return
    now = time.monotonic()
    async with _rate_lock:
        bucket = _creation_log[ip]
        while bucket and now - bucket[0] > WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many voice sessions from this address. Please try again later.",
            )
        bucket.append(now)


async def _maybe_purge(db: AsyncSession) -> None:
    global _last_purge
    now = time.monotonic()
    if now - _last_purge < 600:
        return
    _last_purge = now
    try:
        await purge_expired_public_sessions(db)
    except Exception:
        await db.rollback()


@router.post(
    "/session",
    response_model=SessionCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create an anonymous voice session",
)
async def create_session(
    request: Request,
    payload: SessionCreateRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> SessionCreated:
    await _check_rate_limit(_client_ip(request))
    await _maybe_purge(db)

    session = await create_public_session(db, language=(payload.language if payload else None))
    await db.commit()
    return SessionCreated(
        session_id=session.id,
        language=session.language,
        expires_in_hours=settings.PUBLIC_SESSION_TTL_HOURS,
    )


@router.get("/session/{session_id}", summary="Read public session metadata")
async def read_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")

    turns = await db.scalar(
        select(func.count(Message.id)).where(
            Message.session_id == session_id, Message.role == "user"
        )
    )
    return {
        "session_id": session.id,
        "language": session.language,
        "created_at": session.created_at.isoformat(),
        "expires_at": (
            session.created_at + timedelta(hours=settings.PUBLIC_SESSION_TTL_HOURS)
        ).isoformat(),
        "turns": int(turns or 0),
    }


@router.delete("/session/{session_id}", status_code=status.HTTP_200_OK, summary="End a session")
async def end_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")

    owner_id = session.user_id
    await db.execute(delete(ToolExecution).where(ToolExecution.session_id == session_id))
    await db.execute(delete(Message).where(Message.session_id == session_id))
    await db.execute(
        delete(PendingConfirmation).where(PendingConfirmation.session_id == session_id)
    )
    await db.delete(session)
    if owner_id.startswith("guest-"):
        await db.execute(delete(User).where(User.id == owner_id))
    await db.commit()
    return {"status": "ended", "session_id": session_id}


# ---------------------------------------------------------------------------
# TTS-only endpoint: synthesize a greeting without requiring audio input
# ---------------------------------------------------------------------------

class SpeakRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    text: str = Field(default="Hello! How can I help you today?", max_length=500)


@router.post(
    "/speak",
    summary="Synthesize TTS audio for a greeting or prompt",
    status_code=status.HTTP_200_OK,
)
async def speak(
    payload: SpeakRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return base64-encoded WAV audio for the supplied text without needing
    an audio upload.  Used by the frontend to play a welcome greeting when the
    voice widget is first opened."""

    session = await get_session(db, payload.session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice session not found or expired.",
        )

    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required.")

    try:
        from app.providers import tts
        audio_bytes = await tts.synthesize(text)
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        return {"session_id": payload.session_id, "audio_b64": audio_b64, "mime": "audio/wav"}
    except Exception as exc:
        # Return a graceful fallback so the UI can use browser speechSynthesis
        return {
            "session_id": payload.session_id,
            "audio_b64": None,
            "mime": None,
            "fallback": True,
            "text": text,
            "error": str(exc),
        }
