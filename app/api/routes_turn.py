"""Request-based voice turn endpoint.

Flow: Groq Whisper (STT) -> orchestrator with validated tools -> Gemini (TTS).
The endpoint is public: a visitor only needs a session id, no token.
"""

import base64
import re
import time
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import tool_runtime_context
from app.core.dependencies import (
    get_agent_service,
    get_optional_current_user,
    get_user_llm_config_service,
)
from app.core.logger import logger
from app.core.memory import list_user_memory
from app.core.orchestrator import run_turn
from app.core.session import (
    ensure_voice_user,
    get_session,
    summarize_session_history,
)
from app.db.database import get_db
from app.providers import create_llm, stt, tts
from app.tools.registry import SqlIdempotencyStore, ToolContext
from app.tools.registry_tools import build_registry

router = APIRouter(prefix="/voice", tags=["Voice"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MIN_UTTERANCE_MS = 300


def repeat_response(reason: str) -> dict[str, str]:
    return {
        "status": "repeat",
        "reason": reason,
        "message": "I didn't catch that. Please speak clearly and try again.",
    }


def _spoken_reply(text: str) -> str:
    """Remove common Markdown and URLs before sending text to speech."""
    text = re.sub(r"\[([^\]]+)\]\((?:https?://)?[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"(?m)^\s*[-*•]\s+", "", text)
    return re.sub(r"[*_#`~]", "", text).strip()


@router.post("/turn", summary="Run one complete voice turn")
async def voice_turn(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    session_id: str = Form(...),
    duration_ms: int | None = Form(default=None, ge=0),
    language: str | None = Form(default=None),
    chatbot_id: str | None = Form(default=None),
    current_user: dict | None = Depends(get_optional_current_user),
    config_service=Depends(get_user_llm_config_service),
    agent_service=Depends(get_agent_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept recorded audio and return transcript, spoken reply, audio and timings."""
    started_at = time.perf_counter()

    mime = (audio.content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if not mime:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Audio content type is required.",
        )

    if duration_ms is not None and duration_ms < MIN_UTTERANCE_MS:
        return {"session_id": session_id, "transcript": "", "reply": "", "audio_b64": None, **repeat_response("utterance_too_short")}

    audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)
    if not audio_bytes:
        return {"session_id": session_id, "transcript": "", "reply": "", "audio_b64": None, **repeat_response("empty_audio")}
    if len(audio_bytes) < 200:
        return {"session_id": session_id, "transcript": "", "reply": "", "audio_b64": None, **repeat_response("audio_too_short")}
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio recording exceeds the 25 MB upload limit.",
        )

    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice session not found or expired. Create a new session.",
        )
    if current_user and session.user_id != str(current_user["id"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice session not found or expired. Create a new session.",
        )

    if current_user:
        user_id = str(current_user["id"])
        user_config = await config_service.get_raw_user_config_by_user_id(user_id)
        if not user_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Configure your LLM provider and voice agent model before starting a voice conversation.",
            )
        voice_user = await ensure_voice_user(db, user_id, current_user.get("email"))
        memory_items = await list_user_memory(db, voice_user)
    else:
        user_id = session.user_id
        user_config = settings.public_llm_config()
        if not user_config:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The public voice agent is not configured.",
            )
        memory_items = []

    if language and session.language != language:
        session.language = language
    await db.commit()

    try:
        transcript = await stt.transcribe(audio_bytes, mime, session.language)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    stt_finished = time.perf_counter()
    transcript = transcript.strip()
    if not transcript:
        return {
            "session_id": session.id,
            "transcript": "",
            "reply": "",
            "audio_b64": None,
            "timings_ms": {"stt": round((stt_finished - started_at) * 1000), "llm": 0, "tts": 0},
            **repeat_response("no_speech_detected"),
        }

    llm = create_llm(agent_service, user_config)
    registry = build_registry(authenticated=bool(current_user), allow_search=True)
    ctx = ToolContext(
        session_id=session.id,
        user_id=user_id,
        store=SqlIdempotencyStore(session.id),
        chatbot_id=chatbot_id,
    )
    turn_id = str(uuid4())
    try:
        async with tool_runtime_context(
            user_id=user_id if current_user else None,
            session_id=session.id,
            llm_config=user_config,
            chatbot_id=chatbot_id,
        ):
            reply = await run_turn(
                db,
                session,
                transcript,
                llm,
                registry,
                ctx,
                memory_items=memory_items,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    reply = _spoken_reply(reply) or "Sorry, could you say that again?"
    if current_user:
        background_tasks.add_task(summarize_session_history, session.id, llm)
    llm_finished = time.perf_counter()

    audio_b64 = None
    audio_mime = None
    try:
        audio_out = await tts.synthesize(reply)
        audio_b64 = base64.b64encode(audio_out).decode("ascii")
        audio_mime = "audio/wav"
    except Exception as tts_err:
        logger.warning(f"Voice turn TTS generation fallback: {tts_err}")
    tts_finished = time.perf_counter()
    timings = {
        "stt": round((stt_finished - started_at) * 1000),
        "llm": round((llm_finished - stt_finished) * 1000),
        "tts": round((tts_finished - llm_finished) * 1000),
    }
    logger.info(
        "Voice turn completed",
        extra={
            "session_id": session.id,
            "user_id": user_id,
            "turn_id": turn_id,
            "anonymous": current_user is None,
            "latency_ms": round((tts_finished - started_at) * 1000),
        },
    )

    return {
        "session_id": session.id,
        "transcript": transcript,
        "reply": reply,
        "audio_b64": audio_b64,
        "audio_mime_type": audio_mime,
        "timings_ms": timings,
    }
