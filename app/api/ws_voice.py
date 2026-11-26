"""Public real-time voice WebSocket with VAD, streaming LLM, chunked TTS, and barge-in support."""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
import httpx

from app.core.audio_utils import pcm16_to_wav
from app.core.chunker import extract_phrase, speech_chunks
from app.core.config import settings
from app.core.context import (
    current_chatbot_id,
    current_llm_config,
    current_user_id,
    current_voice_session_id,
    current_search_attempts,
    tool_runtime_context,
)
from app.core.logger import logger
from app.core.session import (
    add_message,
    create_public_session,
    get_session,
    mark_last_assistant_interrupted,
    messages_for_llm,
    summarize_session_history,
)
from app.core.vad import Segmenter
from app.db.database import SessionLocal
from app.db.models import ConversationSession, Message
from app.providers import create_llm, stt, tts
from app.services.agent_service import AgentService
from app.services.prompt_service import PromptService
from app.services.qdrant_service import qdrant_service
from app.utils.tool import web_search, document_search, book_appointment, check_appointment
from app.core.voice_entity_flow import (
    normalize_transcript_symbols,
    VoiceSessionEntityState,
)
from app.tools.preferences import save_preference

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage

router = APIRouter(tags=["Voice WebSocket"])
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")

# Speaker output keeps echoing into the microphone for a moment after the last
# PCM frame is sent; utterances inside this window are screened for self-echo.
ECHO_TAIL_SECONDS = 1.5

FILLER_WORDS = {
    "hmm", "hm", "hmmm", "mm", "mhm", "uh", "um", "erm",
    "uh-huh", "uh huh", "aha", "oh", "oho", "हम्म",
}

# Acknowledgements: ignore them ONLY while the agent is talking.
ACK_WORDS = {
    "ok", "okay", "yes", "yeah", "yep", "yup", "right", "sure", "alright",
    "fine", "cool", "good", "great", "nice", "correct", "exactly", "true",
    "got it", "i see", "i understand", "understood", "makes sense",
    "go on", "go ahead", "continue",
    # Hindi
    "haan", "han", "ha", "haanji", "ji", "achha", "accha", "theek", "thik",
    "theek hai", "thik hai", "हाँ", "हां", "जी", "अच्छा", "ठीक", "ठीक है",
}


def is_backchannel(text: str, while_speaking: bool = False) -> bool:
    cleaned = re.sub(r"[^\w\s]", "", text.lower()).strip()
    if not cleaned:
        return True
    words = cleaned.split()
    if len(words) > 3:
        return False
    pool = (FILLER_WORDS | ACK_WORDS) if while_speaking else FILLER_WORDS
    return cleaned in pool or all(w in pool for w in words)


# Goodbye & Hangup intent patterns
GOODBYE_USER_PATTERNS = [
    r"\b(?:good\s*bye|bye\s*bye|byebye|bye)\b",
    r"\b(?:cut\s+the\s+call|end\s+the\s+call|hang\s*up|disconnect\s+the\s+call|stop\s+the\s+call|close\s+the\s+call)\b",
    r"\b(?:call\s+cut|phone\s+cut|phone\s+rakh|call\s+rakh|call\s+band|call\s+khatam)\b",
    r"\b(?:alvida|chalta\s+hu|chalta\s+hoon|tata|see\s+you\s+later)\b",
    r"\b(?:that(?:'s|\s+is)\s+all(?:,\s*thank\s+you)?(?:\s+bye)?)\b",
    r"\b(?:nothing\s+else(?:,\s*thank\s+you)?(?:\s+bye)?)\b",
]
_GOODBYE_USER_RE = re.compile("|".join(GOODBYE_USER_PATTERNS), re.IGNORECASE)

GOODBYE_ASSISTANT_PATTERNS = [
    r"\[END_CALL\]",
]
_GOODBYE_ASSISTANT_RE = re.compile("|".join(GOODBYE_ASSISTANT_PATTERNS), re.IGNORECASE)


def _is_hangup_intent(text: str) -> bool:
    """Check if the user transcript indicates an intention to hang up or say goodbye."""
    if not text:
        return False
    return bool(_GOODBYE_USER_RE.search(text))


def _is_assistant_goodbye(text: str, user_transcript: str = "") -> bool:
    """Check if the assistant's text is a farewell message or contains [END_CALL]."""
    if user_transcript and _is_hangup_intent(user_transcript):
        return True
    if "[END_CALL]" in text and _is_hangup_intent(user_transcript):
        return True
    return False


VOICE_CALL_RULES = (
    "\n\nVOICE CALL GUIDELINES & 6-STEP VERIFICATION FLOW:\n"
    "- Keep responses brief, direct, and conversational (1 to 2 sentences).\n"
    "- Do NOT use emojis, bullet points, asterisks, or markdown formatting.\n"
    "- Your responses will be read aloud by a text-to-speech engine.\n"
    "- Use available tools whenever you need specific facts or information.\n"
    "- APPOINTMENT BOOKING WORKFLOW (Entity Extraction & User Confirmation):\n"
    "  1. Entity Extraction: When a user wants to book or meet, collect: Name, Email, Contact Phone, Preferred Date/Time, and Reason.\n"
    "  2. Normalization & Validation: The system converts spoken symbols ('at' -> '@', 'dot' -> '.', spoken digits -> clean phone numbers). Ensure email has a valid format and phone has 10+ digits. If any field is missing or invalid, ask for that specific item.\n"
    "  3. USER CONFIRMATION (REQUIRED): Once all 5 fields are ready, you MUST read back the complete normalized values to the user:\n"
    "     'I have noted your appointment details: Name: [Name], Email: [Email], Phone: [Phone], Time: [Time], Reason: [Reason]. "
    "Do you confirm that you would like me to go ahead and book this appointment?'\n"
    "  4. Tool Execution: You are strictly forbidden from saving or booking until the user gives explicit verbal confirmation (e.g. 'yes', 'confirm', 'book it'). Call book_appointment with confirmed=True ONLY after verbal confirmation.\n"
    "- If an appointment already exists for the email, politely let the user know their query is already recorded on file.\n"
    "- APPOINTMENT LOOKUP WORKFLOW:\n"
    "  When a user asks to check, look up, or verify an existing appointment/consultation, or asks when their meeting is scheduled:\n"
    "  1. Ask for their email address if not already provided.\n"
    "  2. Call the `check_appointment` tool with their email address.\n"
    "  3. Read back the appointment status, scheduled date/time, and details warmly and conversationally.\n"
    "- If the user explicitly says goodbye, asks to hang up, or finishes the conversation, give a polite, brief farewell "
    "(e.g. 'Goodbye! Have a great day!' or in Hindi 'अलविदा! आपका दिन शुभ हो!') and append '[END_CALL]' at the end of your message.\n"
    "- CRITICAL: NEVER say goodbye or append '[END_CALL]' if the user is asking questions or continuing the conversation. "
    "Keep the conversation open and ready for the next question."
)


def _spoken_text(text: str) -> str:
    """Keep streamed TTS text plain, omit links/markdown syntax, query rewriter JSON, and [END_CALL] tag."""
    if not text:
        return ""

    # 1. Strip query rewriter JSON blocks if echoed or leaked from tool streams
    text = re.sub(
        r'\{\s*"queries"\s*:\s*\[[\s\S]*?\]\s*,\s*"keywords"\s*:\s*\[[\s\S]*?\]\s*\}\s*',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r'\{\s*"queries"[\s\S]*?\}\s*', '', text, flags=re.IGNORECASE)

    # 2. Strip thinking and tool call markers
    for marker in [
        "<think>", "</think>",
        "<|DSML|>", "</|DSML|>",
        "<function>", "</function>",
        "<tool_call>", "</tool_call>",
    ]:
        text = text.replace(marker, "")
    text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)

    # 3. Strip [END_CALL] tag
    text = re.sub(r"\[END_CALL\]", "", text, flags=re.IGNORECASE)

    # 4. Remove markdown links and bare URLs
    text = re.sub(r"\[([^\]]+)\]\((?:https?://)?[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+|www\.\S+", "", text)

    # 5. Clean list bullets and markdown formatting symbols
    text = re.sub(r"(?m)^\s*[-*•]\s+", "", text)
    text = re.sub(r"[*_#`~]", "", text)

    # 6. Normalize whitespace
    return re.sub(r"\s+", " ", text).strip()


def _normalize_words(text: str) -> list[str]:
    """Tokenize text into lowercase words across all Unicode languages (Hindi, English, etc.)."""
    import unicodedata
    cleaned = "".join(
        c if not unicodedata.category(c).startswith("P") else " "
        for c in text
    )
    return [w.lower() for w in cleaned.split() if w]


def _is_echo_of(transcript: str, assistant_texts: list[str]) -> bool:
    """Detect whether an incoming transcript is the microphone hearing the assistant's own voice."""
    spoken = _normalize_words(transcript)
    if not spoken:
        return False
    reference = _normalize_words(" ".join(assistant_texts[-6:]))
    if not reference:
        return False
    reference_set = set(reference)
    covered = sum(1 for word in spoken if word in reference_set)

    # 1. Exact 1-word echo (e.g. "जी", "yes", "hello", "weather", "price")
    if len(spoken) == 1:
        return spoken[0] in reference_set

    # 2. Multi-word overlap: if 35% or more words were just spoken by assistant
    if (covered / len(spoken)) >= 0.35 and covered >= 1:
        return True

    # 3. Substring / phrase match in normalized text
    spoken_str = " ".join(spoken)
    reference_str = " ".join(reference)
    if spoken_str in reference_str or reference_str in spoken_str:
        return True

    return False


def is_valid_speech_transcript(transcript: str, duration_ms: int = 0) -> bool:
    """Validate whether an STT transcript represents real spoken user content rather than noise or hallucination."""
    if not transcript or not transcript.strip():
        return False
    # Strip whitespace, ASCII punctuation, Hindi danda/double-danda, and symbols
    cleaned = re.sub(
        r"[\s\.\,\!\?\।\॥\-\—\:\;\"\'\(\)\[\]\{\}\<\>\/\\\|`~@#$%^&*+=_]+",
        "",
        transcript,
    )
    if not cleaned:
        return False
    # Filter known Whisper silence hallucinations
    text_lower = transcript.strip().lower().rstrip(".!?, ")
    if text_lower in (
        "thank you",
        "thank you.",
        "thanks",
        "thanks.",
        "thank you so much",
        "thank you very much",
        "thanks for watching",
        "thanks for watching!",
        "thank you for watching",
        "you",
        "subtitles by",
        "subscribe",
        "closed captioning",
        "amara.org",
        "so",
        "the end",
    ):
        return False
    return True


@router.websocket("/ws/voice")
@router.websocket("/voice/ws")
@router.websocket("/ws")
@router.websocket("/ws/pipecat")
@router.websocket("/pipecat/ws")
async def voice_ws(
    ws: WebSocket,
    session_id: str | None = None,
    chatbot_id: str | None = None,
    engine: str | None = None,
):
    """Stream audio for an anonymous guest session; connects directly without prior HTTP setup."""
    await ws.accept()
    logger.info(
        f"Voice WebSocket accepted from {ws.client.host if ws.client else 'unknown'} "
        f"(chatbot_id={chatbot_id or 'none'})"
    )

    session = None
    session_id_val = None
    language = "en"
    for attempt in range(6):
        try:
            async with SessionLocal() as db:
                if session_id:
                    session = await get_session(db, session_id)
                    if session is None or not session.user_id.startswith("guest-"):
                        session = await create_public_session(db)
                        await db.commit()
                else:
                    session = await create_public_session(db)
                    await db.commit()

                expires = session.created_at + timedelta(hours=max(1, settings.PUBLIC_SESSION_TTL_HOURS))
                if expires < datetime.utcnow():
                    await ws.close(code=4408, reason="Voice session expired")
                    return

                session_id_val = session.id
                language = session.language or "en"
                break
        except Exception as exc:
            if attempt < 5 and ("locked" in str(exc).lower() or "busy" in str(exc).lower()):
                wait_time = (attempt + 1) * 0.15
                logger.warning(f"Database busy/locked on session init, retrying in {wait_time:.2f}s... (attempt {attempt + 1}/5)")
                await asyncio.sleep(wait_time)
                continue
            logger.exception(f"Failed to initialize voice session in database: {exc}")
            await ws.close(code=1011, reason="Database session initialization failed")
            return
    session_id = session_id_val

    mongo_db = getattr(ws.app.state, "mongo_db", None)
    chatbot = None
    owner_user_id = None
    llm_config = None
    system_prompt = None
    if chatbot_id and mongo_db is not None:
        try:
            chatbot = await mongo_db["chatbots"].find_one({"_id": chatbot_id})
            if chatbot:
                owner_user_id = chatbot.get("user_id")
                system_prompt = chatbot.get("system_prompt")
                configs = mongo_db["user_llm_configs"]
                config_id = chatbot.get("llm_config_id")
                if config_id and owner_user_id:
                    llm_config = await configs.find_one(
                        {"_id": config_id, "user_id": owner_user_id}
                    )
                if not llm_config and owner_user_id:
                    llm_config = await configs.find_one({"user_id": owner_user_id})
                if llm_config:
                    llm_config.pop("_id", None)
                if not system_prompt or not system_prompt.strip():
                    bot_name = chatbot.get("name", "Support Assistant")
                    system_prompt = f"You are {bot_name}, a helpful AI customer support agent."
        except Exception as exc:
            logger.warning(f"Note: MongoDB chatbot lookup error (ignoring and using default): {exc}")

    active_chatbot_id = chatbot_id if chatbot else None

    if mongo_db is not None:
        try:
            if qdrant_service.mongo_db is None:
                qdrant_service.mongo_db = mongo_db
        except Exception:
            pass

    current_chatbot_id.set(active_chatbot_id)
    current_user_id.set(owner_user_id)
    current_llm_config.set(llm_config)
    current_voice_session_id.set(session_id)

    llm_config = llm_config or settings.public_llm_config()
    if not llm_config:
        logger.error("Public voice agent is not configured: public_llm_config() returned None")
        await ws.close(code=1013, reason="Public voice agent is not configured")
        return

    # Pipecat Voice Agent Flow is the primary voice engine
    is_scratch_explicit = (engine or ws.query_params.get("engine") or "").lower() == "scratch"
    if not is_scratch_explicit:
        logger.info(f"[Voice Flow] Running session {session_id} using Pipecat Voice Agent Flow (default)")
        from app.core.voice_entity_flow import create_pipecat_voice_agent
        pipecat_agent = create_pipecat_voice_agent(
            user_config=llm_config,
            session_id=session_id,
            chatbot_id=active_chatbot_id,
            user_id=owner_user_id,
            system_instruction=system_prompt,
            http_client=getattr(ws.app.state, "http_client", None),
        )
        await pipecat_agent.run_websocket_session(ws, session_id=session_id, initial_language=language)
        return

    segmenter = Segmenter()
    http_client = getattr(ws.app.state, "http_client", None)
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=30.0)
    try:
        agent_service = AgentService(client=http_client, settings=settings)
        llm = create_llm(agent_service, llm_config)
    except Exception as exc:
        logger.exception(f"Voice WebSocket agent initialization failed: {exc}")
        await ws.close(code=1011, reason="Voice agent initialization failed")
        return

    # LangChain agent tools for voice agent (extensible with custom tools)
    voice_tools = [document_search, web_search, save_preference, book_appointment, check_appointment]

    # Initialize LangChain agent using the dedicated voice system prompt template (app/prompts/voice_system_prompt.txt)
    custom_behavior = (
        system_prompt or (chatbot.get("name") + " voice assistant" if chatbot else "AI voice assistant")
    )
    prompt_service = getattr(agent_service, "prompt_service", None) or PromptService()
    base_voice_prompt = prompt_service.get_voice_system_prompt(behavior=custom_behavior)

    voice_model = agent_service._get_llm_model(llm_config)
    voice_agent = create_agent(
        model=voice_model,
        tools=voice_tools,
        system_prompt=base_voice_prompt,
        checkpointer=InMemorySaver(),
    )

    async def retrieve_chatbot_documents(query_text: str) -> str:
        """Search Qdrant knowledge base documents filtered specifically by chatbot_id using the query rewriter and reranker."""
        target_bot = active_chatbot_id or chatbot_id
        if not target_bot or not query_text or not query_text.strip():
            return ""
        try:
            current_chatbot_id.set(target_bot)
            if owner_user_id:
                current_user_id.set(owner_user_id)
            if llm_config:
                current_llm_config.set(llm_config)

            from app.utils.tool import document_search as rag_doc_search, reset_search_counter
            reset_search_counter()

            doc_result = await rag_doc_search.ainvoke({"query": query_text.strip()})
            if doc_result and isinstance(doc_result, str):
                if "RETRIEVAL_STATUS: LOW_CONFIDENCE" not in doc_result and "No relevant information was found" not in doc_result:
                    logger.info(f"[Voice RAG] Retrieved document search result ({len(doc_result)} chars) for chatbot {target_bot}")
                    return doc_result.strip()

            # Fallback direct search if query rewriter returned low confidence
            logger.info(f"[Voice RAG] Running fallback direct search for '{query_text}' (chatbot_id={target_bot})")
            matches = await qdrant_service.similarity_search(
                query=query_text.strip(),
                limit=4,
                chatbot_id=target_bot,
                user_id=None,
            )
            if not matches:
                return ""

            snippets = []
            for item in matches:
                txt = (item.get("text") or "").strip()
                if not txt:
                    continue
                filename = item.get("filename") or "Knowledge Document"
                snippets.append(f"[{filename}]:\n{txt}")

            if not snippets:
                return ""

            logger.info(
                f"[Voice RAG] Retrieved {len(snippets)} document chunk(s) via fallback for query: \"{query_text}\" (chatbot_id={target_bot})"
            )
            return "\n\n".join(snippets[:3])
        except Exception as doc_err:
            logger.warning(f"[Voice RAG] Document retrieval error for chatbot {target_bot}: {doc_err}")
            return ""

    async def execute_web_search(query_text: str) -> str:
        """Search the public web using DuckDuckGo search for real-time external info."""
        if not query_text or not query_text.strip():
            return ""
        clean_query = query_text.strip()
        for prefix in ["can you tell me", "please search", "search for", "look up", "what is", "tell me about"]:
            if clean_query.lower().startswith(prefix):
                clean_query = clean_query[len(prefix):].strip()
        if not clean_query:
            clean_query = query_text.strip()

        try:
            from app.utils.tool import search_api
            logger.info(f"[Voice Web] Searching web for query: \"{clean_query}\"")
            res = await asyncio.wait_for(
                asyncio.to_thread(search_api.run, clean_query),
                timeout=4.0
            )
            if res and isinstance(res, str) and not res.startswith("Error executing web search"):
                logger.info(f"[Voice Web] Retrieved web search result ({len(res)} chars)")
                return res[:1200].strip()
        except asyncio.TimeoutError:
            logger.warning(f"[Voice Web] Web search timed out after 4.0s for '{clean_query}'")
        except Exception as web_err:
            logger.warning(f"[Voice Web] Web search error: {web_err}")
        return ""
    send_lock = asyncio.Lock()
    active: asyncio.Task | None = None
    closed = False
    assistant_audio_active = False
    incoming_audio_chunks = 0
    outgoing_audio_chunks = 0
    # Echo guard: the mic keeps streaming while the agent speaks, so audio that
    # leaves the speakers can come straight back. Track when audio last played
    # and what was said, and ignore matching speech as self-echo.
    last_audio_sent_at = 0.0
    # The client reports when its speaker truly starts and stops; buffered
    # playback keeps echoing long after the last byte was sent.
    client_playing = False
    last_playback_end_at = 0.0
    # Set when VAD confirmed the user interrupted; the next utterance is a real
    # user turn and must not be screened as echo.
    post_barge_in = False
    recent_assistant_text: list[str] = []
    echo_tail_seconds = ECHO_TAIL_SECONDS
    call_ended = False
    last_user_activity = time.monotonic()
    inactivity_prompted = False
    pending_user_transcript = ""
    current_turn_transcript = ""
    INACTIVITY_WARN_TIMEOUT = 18.0
    INACTIVITY_CUT_TIMEOUT = 32.0

    async def send_json(payload: dict) -> None:
        async with send_lock:
            await ws.send_json(payload)

    async def send_state(state: str) -> None:
        """The backend owns the agent state; clients only render it."""
        await send_json({"type": "state", "state": state})

    async def cancel_active() -> None:
        nonlocal active
        if active and not active.done():
            active.cancel()
            try:
                await active
            except asyncio.CancelledError:
                pass
        active = None

    async def send_audio(chunk: bytes) -> None:
        nonlocal outgoing_audio_chunks, last_audio_sent_at
        if not chunk:
            return
        async with send_lock:
            await ws.send_bytes(chunk)
        outgoing_audio_chunks += 1
        last_audio_sent_at = time.monotonic()

    turn_counter = 0
    turn_audio_chunks = 0

    async def stream_sentence_tts(sentence: str) -> None:
        """Stream TTS audio chunks for a sentence or clause group."""
        nonlocal assistant_audio_active, outgoing_audio_chunks, post_barge_in, turn_audio_chunks
        if not sentence.strip():
            return
        cleaned = sentence.strip()
        # Hard guard against speaking the same phrase twice in a turn.
        if recent_assistant_text and recent_assistant_text[-1] == cleaned:
            return
        recent_assistant_text.append(cleaned)
        del recent_assistant_text[:-8]
        chunks_before = outgoing_audio_chunks
        sentence_bytes = 0
        logger.info(f"[TTS] Synthesizing sentence: \"{sentence}\"")
        try:
            async for chunk in tts.stream(sentence):
                if not assistant_audio_active:
                    # First audio frame of this turn: announce state once.
                    post_barge_in = False
                    pending_user_transcript = ""
                    await send_state("speaking")
                assistant_audio_active = True
                sentence_bytes += len(chunk)
                turn_audio_chunks += 1
                await send_audio(chunk)
        except Exception as tts_err:
            logger.warning(f"[TTS] Streaming exception on sentence: {tts_err}")

        if outgoing_audio_chunks > chunks_before:
            logger.info(
                f"[TTS] Streamed {outgoing_audio_chunks - chunks_before} chunks ({sentence_bytes} bytes)"
            )

    async def stream_greeting(text: str) -> None:
        """Stream a greeting or welcome message directly through the WebSocket."""
        nonlocal assistant_audio_active, turn_audio_chunks, turn_counter
        turn_counter += 1
        turn_id = f"turn_{turn_counter}"
        turn_audio_chunks = 0
        recent_assistant_text.clear()
        logger.info(f"[LLM] Greeting ({turn_id}): \"{text}\"")
        try:
            await send_json({"type": "transcript", "role": "assistant", "text": text, "turn_id": turn_id})
            await send_json({
                "type": "audio_start",
                "sample_rate": 24000,
                "channels": 1,
                "format": "pcm_s16le",
                "turn_id": turn_id,
            })
            for sentence in speech_chunks(text):
                await stream_sentence_tts(sentence)

            if turn_audio_chunks == 0:
                logger.info(f"[TTS] Greeting produced no server audio chunks; sending single tts_fallback")
                await send_json({
                    "type": "tts_fallback",
                    "text": text,
                    "turn_id": turn_id,
                })
                client_playing = True
                last_audio_sent_at = time.monotonic()

            assistant_audio_active = False
            await send_json({"type": "unduck_audio"})
            await send_state("idle")
            await send_json({"type": "turn_end", "turn_id": turn_id})
        except Exception as exc:
            logger.warning(f"[TTS] Greeting streaming exception: {exc}")
            if turn_audio_chunks == 0:
                await send_json({
                    "type": "tts_fallback",
                    "text": text,
                    "turn_id": turn_id,
                })
                client_playing = True
                last_audio_sent_at = time.monotonic()
            await send_state("idle")
            await send_json({"type": "turn_end", "turn_id": turn_id})
        finally:
            assistant_audio_active = False
            last_user_activity = time.monotonic()

    async def respond_with_transcript(pcm: bytes, transcript: str) -> None:
        nonlocal assistant_audio_active, turn_audio_chunks, turn_counter, last_user_activity, inactivity_prompted, call_ended, pending_user_transcript, current_turn_transcript
        last_user_activity = time.monotonic()
        inactivity_prompted = False
        duration_ms = len(pcm) * 1000 // 32000

        if not is_valid_speech_transcript(transcript, duration_ms):
            logger.info(f"[STT Guard] Ignored invalid transcript/hallucination: \"{transcript}\" ({duration_ms}ms)")
            await send_state("idle" if not (assistant_audio_active or client_playing) else "speaking")
            return

        if pending_user_transcript:
            full_transcript = f"{pending_user_transcript} {transcript}".strip()
            logger.info(
                f"[STT] Merged accumulated transcript: \"{full_transcript}\" "
                f"(buffered: \"{pending_user_transcript}\", new: \"{transcript}\")"
            )
            pending_user_transcript = ""
        else:
            full_transcript = transcript.strip()

        # Step 3: Deterministic Normalization of spoken transcript symbols (e.g. 'john at gmail dot com' -> 'john@gmail.com', 'nine eight seven...' -> '987...')
        full_transcript = normalize_transcript_symbols(full_transcript)

        current_turn_transcript = full_transcript
        turn_counter += 1
        turn_id = f"turn_{turn_counter}"
        turn_audio_chunks = 0

        logger.info(f"[STT] User transcript ({turn_id}): \"{full_transcript}\"")
        del recent_assistant_text[:-8]
        await send_json({"type": "transcript", "role": "user", "text": full_transcript, "turn_id": turn_id})
        await send_state("thinking")

        spoken: list[str] = []
        baseline_message_id = 0

        # Persist user turn asynchronously in background to eliminate DB write latency from speech path (saves ~40-60ms)
        async def _save_user_turn_bg(s_id: str, text: str, lang: str | None):
            try:
                async with SessionLocal() as db:
                    s = await get_session(db, s_id)
                    if s:
                        if lang and s.language != lang:
                            s.language = lang
                        await add_message(db, session_id=s.id, role="user", content=text)
                        await db.commit()
            except Exception as bg_err:
                logger.warning(f"Background user turn save error: {bg_err}")

        asyncio.create_task(_save_user_turn_bg(session_id, full_transcript, language))

        try:
            # Ensure tool context is active for current chatbot and user
            target_bot = active_chatbot_id or chatbot_id
            current_chatbot_id.set(target_bot)
            if owner_user_id:
                current_user_id.set(owner_user_id)
            if llm_config:
                current_llm_config.set(llm_config)
            current_search_attempts.set(0)

            # System prompt loaded from system_prompt.txt with voice rules
            prompt_sys = base_voice_prompt

            await send_json({
                "type": "audio_start",
                "sample_rate": 24000,
                "channels": 1,
                "format": "pcm_s16le",
                "turn_id": turn_id,
            })

            sentence_buffer = ""
            full_reply_parts: list[str] = []
            logger.info(f"[Voice Agent Stream] Running LangChain agent with tools for turn {turn_id}...")

            try:
                active_tool_depth = 0
                async for event in voice_agent.astream_events(
                    {"messages": [HumanMessage(content=full_transcript)]},
                    {"configurable": {"thread_id": session_id}},
                    version="v2",
                ):
                    event_kind = event.get("event")

                    if event_kind == "on_tool_start":
                        active_tool_depth += 1
                        tool_name = event.get("name", "tool")
                        logger.info(f"[Voice Agent Tool] Executing: {tool_name}")
                        status_msg = (
                            "Searching in uploaded documents..."
                            if tool_name == "document_search"
                            else (
                                "Searching web..."
                                if tool_name == "web_search"
                                else (
                                    "Processing appointment booking..."
                                    if tool_name == "book_appointment"
                                    else (
                                        "Checking appointment status..."
                                        if tool_name == "check_appointment"
                                        else f"Searching with {tool_name}..."
                                    )
                                )
                            )
                        )
                        await send_json({
                            "type": "status",
                            "status": "searching",
                            "tool": tool_name,
                            "message": status_msg,
                            "turn_id": turn_id,
                        })
                        await send_json({
                            "type": "transcript",
                            "role": "assistant",
                            "text": status_msg,
                            "partial": True,
                            "turn_id": turn_id,
                            "is_status": True,
                        })
                        await send_state("thinking")

                    elif event_kind == "on_tool_end":
                        active_tool_depth = max(0, active_tool_depth - 1)
                        tool_name = event.get("name", "tool")
                        logger.info(f"[Voice Agent Tool] Completed: {tool_name}")
                        await send_json({
                            "type": "status",
                            "status": "tool_completed",
                            "tool": tool_name,
                            "turn_id": turn_id,
                        })

                    elif event_kind == "on_chat_model_stream":
                        if active_tool_depth > 0:
                            continue
                        chunk = event.get("data", {}).get("chunk")
                        content = getattr(chunk, "content", None) if chunk else None
                        token = ""
                        if isinstance(content, str):
                            token = content
                        elif isinstance(content, list):
                            token = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")

                        if not token:
                            continue

                        sentence_buffer += token
                        full_reply_parts.append(token)
                        phrase, sentence_buffer = extract_phrase(sentence_buffer, is_first=(len(spoken) == 0))
                        while phrase:
                            phrase_to_send = _spoken_text(phrase)
                            if phrase_to_send:
                                spoken.append(phrase_to_send)
                                running_text = " ".join(spoken).strip()
                                logger.info(f"[Voice Agent Stream] Phrase: \"{phrase_to_send}\"")
                                await send_json({
                                    "type": "transcript",
                                    "role": "assistant",
                                    "text": running_text,
                                    "partial": True,
                                    "turn_id": turn_id,
                                })
                                await stream_sentence_tts(phrase_to_send)
                            phrase, sentence_buffer = extract_phrase(sentence_buffer, is_first=(len(spoken) == 0))

                if sentence_buffer.strip():
                    phrase_to_send = _spoken_text(sentence_buffer)
                    if phrase_to_send:
                        spoken.append(phrase_to_send)
                        running_text = " ".join(spoken).strip()
                        logger.info(f"[Voice Agent Stream] Final phrase: \"{phrase_to_send}\"")
                        await send_json({
                            "type": "transcript",
                            "role": "assistant",
                            "text": running_text,
                            "partial": True,
                            "turn_id": turn_id,
                        })
                        await stream_sentence_tts(phrase_to_send)

            except Exception as stream_err:
                if spoken:
                    logger.warning(f"[Voice Agent Stream] Streaming stopped mid-reply: {stream_err}")
                else:
                    logger.warning(f"[Voice Agent Stream] Streaming error, falling back to agent invoke: {stream_err}")
                    chat_res = await voice_agent.ainvoke(
                        {"messages": [HumanMessage(content=transcript)]},
                        {"configurable": {"thread_id": session_id}},
                    )
                    messages = chat_res.get("messages", []) if isinstance(chat_res, dict) else []
                    last_msg = messages[-1] if messages else None
                    content = getattr(last_msg, "content", "") if last_msg else "I am here to assist you."
                    if not content or not isinstance(content, str):
                        content = "I am here to assist you."
                    full_reply_parts = [content]
                    for sentence in speech_chunks(content):
                        sentence_to_send = _spoken_text(sentence)
                        if sentence_to_send:
                            spoken.append(sentence_to_send)
                            running_text = " ".join(spoken).strip()
                            logger.info(f"[Voice Agent Fallback] Sentence: \"{sentence_to_send}\"")
                            await send_json({
                                "type": "transcript",
                                "role": "assistant",
                                "text": running_text,
                                "partial": True,
                                "turn_id": turn_id,
                            })
                            await stream_sentence_tts(sentence_to_send)

            full_reply = _spoken_text("".join(full_reply_parts)).strip() or " ".join(spoken).strip()
            logger.info(f"[LLM] Completed reply: \"{full_reply}\"")
            await send_json({
                "type": "transcript",
                "role": "assistant",
                "text": full_reply,
                "partial": False,
                "turn_id": turn_id,
            })

            # Save full completed assistant turn
            async with SessionLocal() as db:
                await add_message(db, session_id=session_id, role="assistant", content=full_reply)
                await db.commit()

            if turn_audio_chunks == 0:
                logger.info(f"[TTS] Turn produced no server audio chunks; sending single tts_fallback")
                await send_json({
                    "type": "tts_fallback",
                    "text": full_reply,
                    "turn_id": turn_id,
                })
                client_playing = True
                last_audio_sent_at = time.monotonic()

            assistant_audio_active = False
            await send_json({"type": "unduck_audio"})
            await send_state("idle")
            await send_json({"type": "turn_end", "turn_id": turn_id})
            asyncio.create_task(summarize_session_history(session_id, llm))

            # Reset user activity timer on turn completion
            last_user_activity = time.monotonic()
            inactivity_prompted = False

            raw_reply = "".join(full_reply_parts)
            if _is_assistant_goodbye(raw_reply, user_transcript=full_transcript):
                logger.info(
                    f"[Call Manager] Goodbye intent detected (user_hangup={_is_hangup_intent(full_transcript)}); "
                    f"ending call after playback (session_id={session_id})"
                )
                call_ended = True
                await asyncio.sleep(1.5)
                await send_json({"type": "end_call", "reason": "goodbye", "turn_id": turn_id})
                async with send_lock:
                    try:
                        await ws.close(code=1000, reason="call_ended_goodbye")
                    except Exception:
                        pass
                return

        except asyncio.CancelledError:
            assistant_audio_active = False
            spoken_text = " ".join(spoken).strip()
            if spoken_text:
                logger.info(f"[LLM] Interrupted! Saved spoken context ({len(spoken_text)} chars): \"{spoken_text}\"")
                try:
                    async with SessionLocal() as db:
                        await mark_last_assistant_interrupted(
                            db,
                            session_id,
                            spoken_text,
                            after_message_id=baseline_message_id,
                        )
                    if not closed:
                        try:
                            await send_json({
                                "type": "transcript",
                                "role": "assistant",
                                "text": spoken_text,
                                "interrupted": True,
                            })
                        except Exception:
                            pass
                except Exception as persist_err:
                    logger.warning(f"Note: Could not persist interrupted voice response: {persist_err}")
            raise
        except WebSocketDisconnect:
            return
        except Exception:
            assistant_audio_active = False
            logger.exception("WebSocket voice turn failed", extra={"session_id": session_id})
            if not closed:
                await send_json({"type": "error", "code": "turn_failed"})
                await send_state("idle")
        finally:
            current_turn_transcript = ""

    async def respond(pcm: bytes) -> None:
        """Transcribe and respond to a completed speech utterance."""
        await send_state("thinking")
        wav = pcm16_to_wav(pcm)
        try:
            transcript = (await stt.transcribe(wav, "audio/wav", language)).strip()
        except Exception as exc:
            logger.warning(f"[STT] Transcription error: {exc}")
            transcript = ""
        await respond_with_transcript(pcm, transcript)

    try:
        # 1. Immediately confirm session establishment directly over WebSocket
        await send_json({
            "type": "session_created",
            "session_id": session_id,
            "language": language,
        })
        # 2. Transmit audio format specifications
        await send_json({
            "type": "audio_config",
            "input_sample_rate": 16000,
            "input_channels": 1,
            "input_format": "pcm_s16le",
            "output_sample_rate": 24000,
            "output_channels": 1,
            "output_format": "pcm_s16le",
        })
        logger.info(
            f"Voice WebSocket session ready (session_id={session_id}, chatbot_id={active_chatbot_id or 'none'})"
        )
        while not closed and not call_ended:
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=1.0)
            except asyncio.TimeoutError:
                message = None

            now_mono = time.monotonic()
            speaker_on = assistant_audio_active or client_playing or (active is not None and not active.done())

            # Check silence / inactivity timeout if user has stopped speaking
            if not speaker_on and not call_ended:
                idle_duration = now_mono - last_user_activity
                if idle_duration >= INACTIVITY_CUT_TIMEOUT:
                    call_ended = True
                    logger.info(
                        f"[Call Manager] No voice detected for {idle_duration:.1f}s; ending call on inactivity (session_id={session_id})"
                    )
                    farewell = (
                        "काफी देर से आपकी कोई आवाज़ नहीं आई, इसलिए मैं कॉल समाप्त कर रहा हूँ। अलविदा!"
                        if language == "hi"
                        else "I haven't heard from you in a while, so I will end the call now. Goodbye!"
                    )
                    await send_json({"type": "transcript", "role": "assistant", "text": farewell})
                    await stream_sentence_tts(farewell)
                    await asyncio.sleep(1.5)
                    await send_json({"type": "end_call", "reason": "inactivity"})
                    async with send_lock:
                        try:
                            await ws.close(code=1000, reason="call_ended_inactivity")
                        except Exception:
                            pass
                    break

                elif idle_duration >= INACTIVITY_WARN_TIMEOUT and not inactivity_prompted:
                    inactivity_prompted = True
                    logger.info(f"[Call Manager] Inactivity check-in prompted after {idle_duration:.1f}s silence")
                    checkin = (
                        "क्या आप अभी भी सुन रहे हैं? क्या मैं आपकी कोई और सहायता कर सकता हूँ?"
                        if language == "hi"
                        else "Are you still there? Let me know if you need any help."
                    )
                    await send_json({"type": "transcript", "role": "assistant", "text": checkin})
                    await stream_sentence_tts(checkin)
                    last_user_activity = time.monotonic()
                    await send_state("idle")

            if message is None:
                continue

            if message["type"] == "websocket.disconnect":
                logger.info(f"Voice WebSocket client disconnected (session_id={session_id})")
                break

            if message.get("text") is not None:
                try:
                    payload_json = json.loads(message["text"])
                except json.JSONDecodeError:
                    await send_json({"type": "error", "code": "invalid_json"})
                    continue

                msg_type = payload_json.get("type")

                # Handle client manual hangup / end_call request
                if msg_type in ("end_call", "hangup"):
                    logger.info(f"[Call Manager] Client explicitly requested call hangup (session_id={session_id})")
                    call_ended = True
                    await cancel_active()
                    await send_json({"type": "end_call", "reason": "user_hangup"})
                    async with send_lock:
                        try:
                            await ws.close(code=1000, reason="user_hangup")
                        except Exception:
                            pass
                    break

                # Handle language configuration
                if msg_type == "config":
                    requested_language = payload_json.get("language", language)
                    if requested_language is not None and (
                        not isinstance(requested_language, str)
                        or not _LANGUAGE.fullmatch(requested_language)
                    ):
                        await send_json({"type": "error", "code": "invalid_language"})
                        continue
                    language = requested_language
                    await send_json({"type": "config_ack", "language": language})
                    continue

                # Handle greeting trigger
                if msg_type == "greeting":
                    greeting_text = payload_json.get("text") or "Hello! How can I help you today?"
                    await cancel_active()
                    active = asyncio.create_task(stream_greeting(greeting_text))
                    continue

                # Client reports its real speaker state; playback lags the
                # network, so this is the only reliable echo reference.
                if msg_type == "playback":
                    state_value = payload_json.get("state")
                    if state_value == "start":
                        client_playing = True
                    elif state_value == "end":
                        client_playing = False
                        last_playback_end_at = time.monotonic()
                    continue

                # Handle client interrupt request
                if msg_type == "interrupt":
                    req_turn_id = payload_json.get("turn_id")
                    logger.info(f"[VAD] Client requested interrupt (turn_id={req_turn_id or 'none'}, session_id={session_id})")
                    await cancel_active()
                    assistant_audio_active = False
                    post_barge_in = True
                    await send_json({"type": "interrupt", "turn_id": req_turn_id})
                    await send_state("listening")
                    continue

                await send_json({"type": "error", "code": "unsupported_message"})
                continue

            data = message.get("bytes")
            if data is None:
                continue
            if not data or len(data) > 64 * 1024 or len(data) % 2:
                await send_json({"type": "error", "code": "invalid_audio_frame"})
                continue

            incoming_audio_chunks += 1

            # Check VAD events. While the assistant is speaking use the stricter
            # barge-in threshold; during the short echo tail the mic goes back to
            # normal sensitivity but utterances are still screened for self-echo.
            # The agent is "speaking" while the server is streaming TTS AND while
            # the client still has audio buffered in its speaker.
            now_mono = time.monotonic()
            # Watchdog: never let a lost "playback end" mute the microphone.
            if client_playing and now_mono - last_audio_sent_at > 30:
                client_playing = False
            speaker_on = assistant_audio_active or client_playing
            last_sound_at = max(last_audio_sent_at, last_playback_end_at)
            is_speaking = speaker_on
            in_echo_window = speaker_on or (
                last_sound_at > 0 and now_mono - last_sound_at < echo_tail_seconds
            )

            for event, payload in segmenter.feed(
                data, is_assistant_speaking=is_speaking
            ):
                if event == "speech_start":
                    logger.info(f"[VAD] Speech started")
                    last_user_activity = time.monotonic()
                    inactivity_prompted = False
                    await send_json({"type": "speech_start"})
                    await send_state("listening")
                    if is_speaking:
                        # Soft duck only – do NOT cancel yet
                        await send_json({"type": "duck_audio"})

                elif event == "barge_in":
                    # Provisional only. Real decision happens on the utterance.
                    if is_speaking:
                        logger.info("[VAD] Possible barge-in (waiting for utterance confirmation)")
                        await send_json({"type": "duck_audio"})
                        # Do NOT cancel_active() and do NOT set post_barge_in here

                elif event == "utterance" and payload:
                    last_user_activity = time.monotonic()
                    inactivity_prompted = False
                    duration_ms = len(payload) * 1000 // 32000

                    logger.info(
                        f"[VAD] Utterance detected: {duration_ms}ms"
                    )

                    # Check speech whenever the assistant is playing
                    # or recently finished playing.
                    if in_echo_window:
                        try:
                            wav_check = pcm16_to_wav(payload)

                            quick_transcript = (
                                await stt.transcribe(
                                    wav_check,
                                    "audio/wav",
                                    language
                                )
                            ).strip()

                        except Exception as exc:
                            logger.warning(
                                f"[Echo Guard] STT validation failed: {exc}"
                            )
                            quick_transcript = ""

                        if not is_valid_speech_transcript(quick_transcript, duration_ms):
                            logger.info(f"[Echo Guard] Discarded invalid transcript/hallucination: '{quick_transcript}' ({duration_ms}ms)")
                            await send_json({"type": "unduck_audio"})
                            await send_state("speaking" if speaker_on else "idle")
                            continue

                        is_echo = _is_echo_of(
                            quick_transcript,
                            recent_assistant_text
                        )

                        awaiting_answer = (
                            (active is None or active.done())
                            and recent_assistant_text
                            and recent_assistant_text[-1].rstrip().endswith("?")
                        )

                        is_noise = (
                            speaker_on
                            and not awaiting_answer
                            and (
                                not quick_transcript
                                or is_backchannel(quick_transcript, while_speaking=True)
                            )
                        )

                        if is_echo or is_noise:
                            logger.info(f"[Echo Guard] Ignored: '{quick_transcript or 'noise'}'")
                            await send_json({"type": "unduck_audio"})
                            # Don't tell the client "idle" while its speaker is still playing
                            await send_state("speaking" if speaker_on else "idle")
                            continue

                        # Speech passed validation.
                        logger.info(
                            f"[Echo Guard] Genuine speech detected: "
                            f"'{quick_transcript}'"
                        )

                        if speaker_on:
                            await cancel_active()

                            assistant_audio_active = False

                            await send_json({"type": "unduck_audio"})
                            await send_json({"type": "interrupt"})

                        post_barge_in = False
                        pending_user_transcript = ""

                        if quick_transcript:
                            active = asyncio.create_task(
                                respond_with_transcript(
                                    payload,
                                    quick_transcript
                                )
                            )
                        else:
                            active = asyncio.create_task(respond(payload))

                        continue

                    # Normal user speech when the assistant is not speaking.
                    if active and not active.done() and not assistant_audio_active and not client_playing:
                        # User spoke again before assistant replied with audio;
                        # preserve current_turn_transcript to combine the thoughts.
                        if current_turn_transcript:
                            pending_user_transcript = current_turn_transcript
                            logger.info(
                                f"[Speech Buffer] User resumed speaking before assistant replied; buffering thought: \"{pending_user_transcript}\""
                            )
                    else:
                        pending_user_transcript = ""

                    await cancel_active()

                    post_barge_in = False

                    active = asyncio.create_task(respond(payload))
                elif event == "utterance_too_long":
                    await send_json({"type": "error", "code": "utterance_too_long"})
    except WebSocketDisconnect:
        pass
    finally:
        closed = True
        logger.info(
            f"Voice WebSocket closed (session_id={session_id})"
        )
        if active and not active.done():
            active.cancel()
            try:
                await active
            except asyncio.CancelledError:
                pass

