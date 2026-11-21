"""FastAPI routes for Pipecat Voice Agent integration.

Provides endpoints for Pipecat frontend clients (Daily and WebRTC transports),
session provisioning, and dynamic custom LLM injection based on user configuration.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logger import logger
from app.core.pipecat_voice_agent import (
    PIPECAT_AVAILABLE,
    PipecatVoiceAgent,
    run_bot,
)

router = APIRouter(prefix="/pipecat", tags=["Pipecat Voice Agent"])


class ConnectRequest(BaseModel):
    transport: Optional[str] = Field(default="daily", description="Transport type: 'daily' or 'webrtc'")
    user_id: Optional[str] = Field(default=None, description="Optional user ID to load custom LLM config")
    chatbot_id: Optional[str] = Field(default=None, description="Optional chatbot ID")
    session_id: Optional[str] = Field(default=None, description="Optional voice session ID")
    custom_llm: Optional[Dict[str, Any]] = Field(default=None, description="Direct custom LLM config overrides")
    room_url: Optional[str] = Field(default=None, description="Optional existing Daily room URL")


class ConnectResponse(BaseModel):
    success: bool
    transport: str
    room_url: Optional[str] = None
    token: Optional[str] = None
    session_id: Optional[str] = None
    message: Optional[str] = None


async def _fetch_user_config(user_id: Optional[str]) -> Dict[str, Any]:
    """Retrieve saved user LLM configuration from MongoDB if available."""
    if not user_id:
        return {}
    try:
        from app.db.mongodb import db
        if db.database is not None:
            config_doc = await db.database["user_llm_configs"].find_one({"user_id": user_id})
            if config_doc:
                return dict(config_doc)
    except Exception as e:
        logger.warning(f"Could not retrieve user LLM config for {user_id}: {e}")
    return {}


async def _create_daily_room_and_token(room_name: Optional[str] = None) -> tuple[str, str]:
    """Create a temporary room and token via the Daily REST API."""
    daily_api_key = os.getenv("DAILY_API_KEY")
    if not daily_api_key:
        fallback_url = os.getenv("DAILY_SAMPLE_ROOM_URL") or os.getenv("DAILY_ROOM_URL")
        if fallback_url:
            return fallback_url, ""
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="DAILY_API_KEY is not configured in .env. Please set DAILY_API_KEY or DAILY_ROOM_URL.",
        )

    headers = {
        "Authorization": f"Bearer {daily_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Create a room that expires in 1 hour
        room_payload = {
            "properties": {
                "exp": int(asyncio.get_event_loop().time() + 3600),
                "enable_chat": True,
            }
        }
        if room_name:
            room_payload["name"] = room_name

        res = await client.post("https://api.daily.co/v1/rooms", json=room_payload, headers=headers)
        if res.status_code not in (200, 201):
            logger.error(f"Failed to create Daily room: {res.text}")
            raise HTTPException(status_code=502, detail=f"Daily room creation failed: {res.text}")

        room_data = res.json()
        room_url = room_data.get("url")
        created_room_name = room_data.get("name")

        # 2. Create meeting token for client
        token_payload = {
            "properties": {
                "room_name": created_room_name,
                "is_owner": False,
            }
        }
        tok_res = await client.post("https://api.daily.co/v1/meeting-tokens", json=token_payload, headers=headers)
        token = tok_res.json().get("token", "") if tok_res.status_code in (200, 201) else ""

        return room_url, token


@router.post("/connect", response_model=ConnectResponse, summary="Connect Pipecat client")
async def connect(payload: ConnectRequest) -> ConnectResponse:
    """Initializes a Pipecat session for the client.

    Retrieves custom LLM settings for the user, resolves room credentials for Daily,
    and returns connection parameters to the Pipecat frontend.
    """
    user_config = await _fetch_user_config(payload.user_id)
    if payload.custom_llm:
        user_config.update(payload.custom_llm)

    transport_type = (payload.transport or "daily").lower()

    if transport_type == "daily":
        if payload.room_url:
            room_url = payload.room_url
            token = ""
        else:
            try:
                room_url, token = await _create_daily_room_and_token()
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error provisioning Daily room: {e}")
                room_url = os.getenv("DAILY_ROOM_URL", "https://yourdomain.daily.co/default-room")
                token = ""

        # Launch background bot worker for this room if Daily is configured
        if PIPECAT_AVAILABLE and room_url and os.getenv("DAILY_API_KEY"):
            try:
                # Spawn Pipecat bot task to join the Daily room
                from pipecat.transports.daily.transport import DailyParams, DailyTransport
                from pipecat.runner.types import RunnerArguments

                async def _start_bot_in_background():
                    try:
                        daily_transport = DailyTransport(
                            room_url=room_url,
                            token=token,
                            bot_name="Support Bot",
                            params=DailyParams(
                                audio_in_enabled=True,
                                audio_out_enabled=True,
                                video_out_enabled=True,
                                video_out_width=1024,
                                video_out_height=576,
                            ),
                        )
                        agent = PipecatVoiceAgent(
                            transport=daily_transport,
                            runner_args=RunnerArguments(),
                            user_config=user_config,
                        )
                        await agent.run()
                    except Exception as bot_err:
                        logger.error(f"Error running background Pipecat bot: {bot_err}")

                asyncio.create_task(_start_bot_in_background())
            except Exception as launch_err:
                logger.warning(f"Could not auto-spawn Pipecat bot worker: {launch_err}")

        return ConnectResponse(
            success=True,
            transport="daily",
            room_url=room_url,
            token=token,
            session_id=payload.session_id,
            message="Daily room ready for connection",
        )

    elif transport_type == "webrtc":
        return ConnectResponse(
            success=True,
            transport="webrtc",
            session_id=payload.session_id,
            message="WebRTC transport selected. Ready for signaling handshake.",
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported transport '{transport_type}'. Supported: 'daily', 'webrtc'",
        )


@router.get("/status", summary="Pipecat service health & capability status")
async def get_status() -> Dict[str, Any]:
    """Inspect current Pipecat capability and provider credentials."""
    return {
        "pipecat_available": PIPECAT_AVAILABLE,
        "transports_supported": ["daily", "webrtc", "websocket"],
        "providers": {
            "daily_configured": bool(os.getenv("DAILY_API_KEY") or os.getenv("DAILY_ROOM_URL")),
            "deepgram_stt_configured": bool(os.getenv("DEEPGRAM_API_KEY") or os.getenv("DEEPGRAM_API")),
            "elevenlabs_tts_configured": bool(os.getenv("ELEVENLABS_API_KEY")),
            "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
            "groq_configured": bool(os.getenv("GROQ_API_KEY")),
            "openrouter_configured": bool(os.getenv("OPEN_ROUTER_API_KEY")),
        },
    }


@router.post("/turn", summary="Process one turn using Pipecat voice flow")
async def pipecat_turn(
    audio: UploadFile = File(...),
    session_id: str = Form(...),
    language: Optional[str] = Form(default="en"),
    chatbot_id: Optional[str] = Form(default=None),
    user_id: Optional[str] = Form(default=None),
) -> Dict[str, Any]:
    """Execute a single voice turn with STT -> Entity Normalization -> Custom LLM -> TTS."""
    import base64
    from app.core.voice_entity_flow import create_pipecat_voice_agent

    audio_bytes = await audio.read()
    user_config = await _fetch_user_config(user_id)

    agent = create_pipecat_voice_agent(
        user_config=user_config,
        session_id=session_id,
        chatbot_id=chatbot_id,
        user_id=user_id,
    )

    result = await agent.process_turn(audio_bytes, language=language or "en", session_id=session_id)
    audio_b64 = base64.b64encode(result["audio_bytes"]).decode("ascii") if result.get("audio_bytes") else None

    return {
        "session_id": session_id,
        "transcript": result["transcript"],
        "reply": result["reply"],
        "audio_b64": audio_b64,
        "mime": "audio/wav",
        "engine": "pipecat",
    }


