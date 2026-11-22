#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""simple-chatbot - Pipecat Voice Agent Pipeline and Orchestration.

This module implements the Pipecat-based voice agent pipeline:
- Real-time audio/video interaction through Daily, WebRTC, or WebSocket
- Animated robot avatar / fallback visual state
- Speech-to-Text using Deepgram or Groq
- Customizable LLM (OpenAI, Anthropic, Gemini, Groq, OpenRouter, or custom endpoint)
  configured dynamically per user configuration
- Deterministic voice entity normalization integrated with voice_entity_flow
- Text-to-Speech using ElevenLabs, Deepgram, or Google Cloud

The bot is encapsulated in the `PipecatVoiceAgent` class (converted from `run_bot`)
with support for a `custom_llm` parameter and `user_config` dictionary.

Run the bot directly using:
    python -m app.core.pipecat_voice_agent
or
    uv run app/core/pipecat_voice_agent.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional, Sequence, Union

from dotenv import load_dotenv

load_dotenv(override=True)

# Safe imports for loguru and PIL
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("pipecat_voice_agent")

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

# Safe imports for Pipecat framework components
try:
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
        Frame,
        LLMRunFrame,
        OutputImageRawFrame,
        SpriteFrame,
        TextFrame,
        TranscriptionFrame,
    )
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
    from pipecat.runner.types import RunnerArguments
    from pipecat.runner.utils import create_transport
    from pipecat.services.deepgram.stt import DeepgramSTTService
    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.transports.base_transport import BaseTransport, TransportParams
    from pipecat.transports.daily.transport import DailyParams
    from pipecat.workers.runner import WorkerRunner
    PIPECAT_AVAILABLE = True
except ImportError as err:
    PIPECAT_AVAILABLE = False
    logger.warning(
        f"Pipecat modules not found ({err}). Install pipecat-ai: "
        "pip install \"pipecat-ai[daily,openai,deepgram,elevenlabs,silero]\""
    )
    # Define placeholder classes so module loads cleanly
    FrameProcessor = object  # type: ignore
    Frame = object  # type: ignore
    FrameDirection = object  # type: ignore
    BaseTransport = object  # type: ignore
    RunnerArguments = object  # type: ignore
    DailyParams = object  # type: ignore
    TransportParams = object  # type: ignore

# Deterministic normalization from voice_entity_flow
try:
    from app.core.voice_entity_flow import normalize_transcript_symbols
except ImportError:
    def normalize_transcript_symbols(text: str) -> str:
        return text

try:
    from app.core.chunker import extract_phrase, speech_chunks
except ImportError:
    def extract_phrase(text: str, is_first: bool = False):
        return text, ""
    def speech_chunks(text: str, max_chars: int = 200):
        return [text]

import re

# Voice Call Guidelines & 6-Step Verification Rules
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

GOODBYE_USER_PATTERNS = [
    r"\b(?:good\s*bye|bye\s*bye|byebye)\b",
    r"\b(?:cut\s+the\s+call|end\s+the\s+call|hang\s*up|disconnect\s+the\s+call|stop\s+the\s+call|close\s+the\s+call)\b",
    r"\b(?:alvida|call\s*khatam|call\s*kaat|call\s*end)\b",
    r"(?:अलविदा|कॉल\s*काट|कॉल\s*समाप्त|कॉल\s*बंद)",
]
_GOODBYE_USER_RE = re.compile("|".join(GOODBYE_USER_PATTERNS), re.IGNORECASE)

def _is_hangup_intent(text: str) -> bool:
    """Check if the user transcript explicitly indicates an intention to hang up or say goodbye."""
    if not text:
        return False
    return bool(_GOODBYE_USER_RE.search(text))

def _is_assistant_goodbye(text: str, user_transcript: str = "") -> bool:
    """Check if the session should conclude with a farewell. Never end call on casual polite phrases."""
    # Only end call if the user explicitly requested hangup/goodbye, or assistant output [END_CALL] after a user goodbye
    if user_transcript and _is_hangup_intent(user_transcript):
        return True
    if "[END_CALL]" in text and _is_hangup_intent(user_transcript):
        return True
    return False

# In-memory cache for verbal tool filler audio chunks (e.g. "I am searching in the documents...")
_FILLER_AUDIO_CACHE: Dict[str, bytes] = {}

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

    # 4. Convert markdown links [title](url) -> title and remove bare URLs
    text = re.sub(r"\[([^\]]+)\]\((?:https?://)?[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+|www\.\S+", "", text)

    # 5. Clean list bullets and markdown formatting symbols
    text = re.sub(r"(?m)^\s*[-*•]\s+", "", text)
    text = re.sub(r"[*_#`~]", "", text)

    # 6. Normalize whitespace
    return re.sub(r"\s+", " ", text).strip()


def is_valid_speech_transcript(transcript: str) -> bool:
    """Validate whether an STT transcript represents real spoken user content rather than noise or Whisper hallucination."""
    if not transcript or not transcript.strip():
        return False
    # Strip whitespace, ASCII punctuation, Hindi danda/double-danda, and symbols
    cleaned = re.sub(
        r"[\s\.\,\!\?\।\॥\-\—\:\;\"\'\(\)\[\]\{\}\<\>\/\\\|`~@#$%^&*+=_]+",
        "",
        transcript,
    )
    # If no alphanumeric characters exist (e.g. just "." or "?"), it's noise
    if not cleaned or not any(c.isalnum() for c in cleaned):
        return False

    text_lower = transcript.strip().lower().rstrip(".!?, ")
    # Known Whisper silence / ambient noise hallucinations
    WHISPER_HALLUCINATIONS = {
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
    }
    if text_lower in WHISPER_HALLUCINATIONS:
        return False

    return True


def _normalize_words(text: str) -> list[str]:
    """Tokenize text into lowercase words across all Unicode languages (Hindi, English, etc.)."""
    import unicodedata
    cleaned = "".join(
        c if not unicodedata.category(c).startswith("P") else " "
        for c in text
    )
    return [w.lower() for w in cleaned.split() if w]


_COMMON_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "her", "its", "our", "their", "mine", "yours", "ours",
    "can", "could", "will", "would", "shall", "should", "may", "might", "must",
    "do", "does", "did", "have", "has", "had", "to", "of", "in", "for", "on", "with",
    "at", "by", "from", "up", "about", "into", "over", "after", "and", "or", "but",
    "so", "what", "which", "who", "whom", "this", "that", "these", "those", "how",
    "why", "when", "where", "tell", "please", "just", "now", "well", "hi", "hello"
}


def _is_echo_of(transcript: str, assistant_texts: list[str]) -> bool:
    """Detect whether an incoming transcript is an exact acoustic echo of the assistant's speech.
    
    Never rejects short user answers (e.g. 'yes', 'no', 'stop', 'help') or user questions
    that contain common conversational words.
    """
    spoken = _normalize_words(transcript)
    if not spoken or len(spoken) < 3:
        # Never reject short 1 or 2 word user utterances
        return False

    spoken_non_stop = [w for w in spoken if w not in _COMMON_STOPWORDS]
    if not spoken_non_stop:
        return False

    reference = _normalize_words(" ".join(assistant_texts[-4:]))
    if not reference:
        return False

    spoken_str = " ".join(spoken)
    reference_str = " ".join(reference)

    # 1. Exact 4-word consecutive sequence match (true acoustic echo)
    if len(spoken) >= 4:
        for i in range(len(spoken) - 3):
            four_gram = " ".join(spoken[i:i + 4])
            if four_gram in reference_str:
                return True

    # 2. Complete verbatim phrase echo
    if len(spoken_non_stop) >= 3 and spoken_str in reference_str:
        return True

    return False



# ============================================================================
# Sprite & Animation Asset Loader
# ============================================================================

sprites: List[Any] = []
script_dir = os.path.dirname(os.path.abspath(__file__))
assets_dir = os.path.join(script_dir, "assets")

quiet_frame = None
talking_frame = None

if PIPECAT_AVAILABLE:
    # 1. Try to load robot sequential frames from assets/robot01.png..robot025.png
    if os.path.exists(assets_dir) and Image is not None:
        for i in range(1, 26):
            full_path = os.path.join(assets_dir, f"robot0{i}.png" if i < 10 else f"robot{i}.png")
            if os.path.exists(full_path):
                try:
                    with Image.open(full_path) as img:
                        sprites.append(
                            OutputImageRawFrame(image=img.tobytes(), size=img.size, format=img.format or "RGB")
                        )
                except Exception as e:
                    logger.warning(f"Could not load sprite {full_path}: {e}")

    # 2. If assets are not found on disk, generate friendly fallback synthetic frames
    if not sprites and Image is not None:
        def _create_synthetic_robot_frame(mouth_open: bool = False) -> Any:
            w, h = 512, 512
            img = Image.new("RGB", (w, h), color=(15, 23, 42))  # Slate dark bg
            draw = ImageDraw.Draw(img)
            # Head
            draw.rounded_rectangle([156, 120, 356, 320], radius=32, fill=(99, 102, 241), outline=(129, 140, 248), width=4)
            # Eyes
            draw.ellipse([196, 180, 236, 220], fill=(255, 255, 255))
            draw.ellipse([276, 180, 316, 220], fill=(255, 255, 255))
            draw.ellipse([210, 192, 226, 208], fill=(15, 23, 42))
            draw.ellipse([290, 192, 306, 208], fill=(15, 23, 42))
            # Mouth
            if mouth_open:
                draw.rounded_rectangle([216, 250, 296, 280], radius=10, fill=(239, 68, 68))
            else:
                draw.line([216, 265, 296, 265], fill=(255, 255, 255), width=6)
            return OutputImageRawFrame(image=img.tobytes(), size=(w, h), format="RGB")

        try:
            quiet_synth = _create_synthetic_robot_frame(mouth_open=False)
            talking_synth = _create_synthetic_robot_frame(mouth_open=True)
            sprites = [quiet_synth, talking_synth]
        except Exception:
            sprites = []

    if sprites:
        flipped = sprites[::-1]
        sprites.extend(flipped)
        quiet_frame = sprites[0]
        talking_frame = SpriteFrame(images=sprites)


# ============================================================================
# Talking Animation Frame Processor
# ============================================================================

if PIPECAT_AVAILABLE:
    class TalkingAnimation(FrameProcessor):
        """Manages the bot's visual animation states.

        Switches between static (listening) and animated (talking) states based on
        the bot's current speaking status.
        """

        def __init__(self):
            super().__init__()
            self._is_talking = False

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)

            if isinstance(frame, BotStartedSpeakingFrame):
                if not self._is_talking and talking_frame:
                    await self.push_frame(talking_frame)
                    self._is_talking = True
            elif isinstance(frame, BotStoppedSpeakingFrame):
                if quiet_frame:
                    await self.push_frame(quiet_frame)
                self._is_talking = False

            await self.push_frame(frame, direction)


    class VoiceEntityTranscriptProcessor(FrameProcessor):
        """Pre-processes transcribed speech frames using deterministic normalization.

        Converts spoken emails ("john at gmail dot com" -> "john@gmail.com")
        and spoken phone digit words ("nine eight seven..." -> "987...")
        before feeding into the LLM context.
        """

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)

            if isinstance(frame, TranscriptionFrame) and getattr(frame, "text", None):
                normalized = normalize_transcript_symbols(frame.text)
                if normalized != frame.text:
                    frame.text = normalized
            elif isinstance(frame, TextFrame) and getattr(frame, "text", None):
                normalized = normalize_transcript_symbols(frame.text)
                if normalized != frame.text:
                    frame.text = normalized

            await self.push_frame(frame, direction)

else:
    class TalkingAnimation:  # type: ignore
        pass

    class VoiceEntityTranscriptProcessor:  # type: ignore
        pass


# ============================================================================
# Transport Parameters Configuration
# ============================================================================

transport_params = {
    "daily": lambda: DailyParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        video_out_enabled=True,
        video_out_width=1024,
        video_out_height=576,
    ) if PIPECAT_AVAILABLE else None,
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        video_out_enabled=True,
        video_out_width=1024,
        video_out_height=576,
    ) if PIPECAT_AVAILABLE else None,
}


# ============================================================================
# Pipecat Voice Agent Class (Converted from run_bot)
# ============================================================================

class PipecatVoiceAgent:
    """Pipecat Voice Agent Pipeline Orchestrator.

    Converted from the standalone `run_bot` function into an extensible class.
    Accepts:
        - `transport`: WebRTC, Daily transport, or None (for WebSocket/turn execution)
        - `runner_args`: RunnerArguments for idle timeout and signal handling
        - `custom_llm`: Custom LLM instance, class, or callable
        - `user_config`: User LLM configuration dict (from DB or request)
        - `system_instruction`: Custom system instruction prompt
        - `stt_service`: Optional custom STT service (Deepgram / Groq)
        - `tts_service`: Optional custom TTS service (ElevenLabs / Deepgram)
        - `enable_animation`: Whether to include avatar video frames
    """

    def __init__(
        self,
        transport: Optional[BaseTransport] = None,
        runner_args: Optional[RunnerArguments] = None,
        custom_llm: Optional[Any] = None,
        user_config: Optional[Dict[str, Any]] = None,
        system_instruction: Optional[str] = None,
        stt_service: Optional[Any] = None,
        tts_service: Optional[Any] = None,
        enable_animation: bool = True,
        initial_greeting: Optional[str] = "Start by introducing yourself.",
        session_id: Optional[str] = None,
        chatbot_id: Optional[str] = None,
        user_id: Optional[str] = None,
        language: str = "en",
    ):
        self.transport = transport
        self.runner_args = runner_args or (RunnerArguments() if PIPECAT_AVAILABLE else None)
        self.custom_llm = custom_llm
        self.user_config = dict(user_config or {})
        self.system_instruction = system_instruction
        self.stt_service = stt_service
        self.tts_service = tts_service
        self.enable_animation = enable_animation
        self.initial_greeting = initial_greeting
        self.session_id = session_id
        self.chatbot_id = chatbot_id
        self.user_id = user_id
        self.language = language or "en"

        self.context: Optional[LLMContext] = None
        self.pipeline: Optional[Pipeline] = None
        self.worker: Optional[PipelineWorker] = None
        self.runner: Optional[WorkerRunner] = None

    def build_llm_service(self) -> Any:
        """Resolve and build the LLM service based on custom_llm and user_config."""
        # 1. If custom_llm is already an instantiated Pipecat LLM service / FrameProcessor, use directly
        if self.custom_llm is not None:
            if hasattr(self.custom_llm, "process_frame") or hasattr(self.custom_llm, "can_generate_metrics"):
                logger.info("Using provided custom_llm instance directly in Pipecat pipeline.")
                return self.custom_llm

            # If custom_llm is a dict, merge it into user_config
            if isinstance(self.custom_llm, dict):
                merged_config = {**self.user_config, **self.custom_llm}
            elif isinstance(self.custom_llm, str):
                merged_config = {**self.user_config, "model": self.custom_llm}
            else:
                merged_config = self.user_config
        else:
            merged_config = self.user_config

        # 2. Determine system prompt using PromptService with dedicated voice prompt
        try:
            from app.services.prompt_service import PromptService
            custom_behavior = (
                self.system_instruction or merged_config.get("system_prompt") or "AI voice assistant"
            )
            sys_prompt = PromptService().get_voice_system_prompt(behavior=custom_behavior)
        except Exception:
            sys_prompt = (
                (self.system_instruction or merged_config.get("system_prompt") or "AI voice assistant")
                + VOICE_CALL_RULES
            )

        config_type = merged_config.get("config_type", "provider")
        provider = (merged_config.get("provider") or "").lower()
        api_key = merged_config.get("api_key")
        base_url = merged_config.get("base_url")
        model = (
            merged_config.get("voice_agent_model")
            or merged_config.get("model")
            or merged_config.get("default_model")
        )

        if not PIPECAT_AVAILABLE:
            return None

        # 3. Custom endpoint (e.g. OpenRouter, DeepSeek, Local Ollama/vLLM)
        if config_type == "custom" or base_url:
            resolved_key = (
                api_key
                or os.getenv("OPEN_ROUTER_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or "default"
            )
            resolved_base_url = base_url or os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            resolved_model = model or "openai/gpt-4o-mini"
            logger.info(f"Pipecat using custom LLM endpoint: model={resolved_model}, url={resolved_base_url}")
            return OpenAILLMService(
                api_key=resolved_key,
                base_url=resolved_base_url,
                model=resolved_model,
                settings=OpenAILLMService.Settings(
                    system_instruction=sys_prompt,
                ),
            )

        # 4. Anthropic provider
        if provider == "anthropic":
            try:
                from pipecat.services.anthropic.llm import AnthropicLLMService
                resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY")
                logger.info(f"Pipecat using Anthropic LLM: model={model or 'claude-3-5-sonnet-latest'}")
                return AnthropicLLMService(
                    api_key=resolved_key,
                    model=model or "claude-3-5-sonnet-latest",
                    settings=AnthropicLLMService.Settings(
                        system_instruction=sys_prompt,
                    ),
                )
            except ImportError:
                logger.warning("AnthropicLLMService not installed in Pipecat; falling back to OpenAILLMService")

        # 5. Gemini / Google provider
        if provider == "gemini":
            try:
                from pipecat.services.google.llm import GoogleLLMService
                resolved_key = api_key or os.getenv("GEMINI_API_KEY")
                logger.info(f"Pipecat using Google Gemini LLM: model={model or 'gemini-1.5-flash'}")
                return GoogleLLMService(
                    api_key=resolved_key,
                    model=model or "gemini-1.5-flash",
                    settings=GoogleLLMService.Settings(
                        system_instruction=sys_prompt,
                    ),
                )
            except ImportError:
                logger.warning("GoogleLLMService not installed in Pipecat; falling back to OpenAILLMService")

        # 6. Groq Provider
        if provider == "groq" or (not api_key and os.getenv("GROQ_API_KEY") and not os.getenv("OPENAI_API_KEY")):
            resolved_key = api_key or os.getenv("GROQ_API_KEY")
            logger.info("Pipecat using Groq OpenAI-compatible LLM endpoint.")
            return OpenAILLMService(
                api_key=resolved_key,
                base_url="https://api.groq.com/openai/v1",
                model=model or "llama-3.3-70b-versatile",
                settings=OpenAILLMService.Settings(
                    system_instruction=sys_prompt,
                ),
            )

        # 7. Default: OpenAI LLM Service
        resolved_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_ROUTER_API_KEY")
        resolved_model = model or "gpt-4o-mini"
        logger.info(f"Pipecat using OpenAILLMService with model={resolved_model}")
        return OpenAILLMService(
            api_key=resolved_key,
            model=resolved_model,
            settings=OpenAILLMService.Settings(
                system_instruction=sys_prompt,
            ),
        )

    def build_stt_service(self) -> Any:
        """Resolve Speech-to-Text service."""
        if self.stt_service is not None:
            return self.stt_service

        if not PIPECAT_AVAILABLE:
            return None

        deepgram_key = os.getenv("DEEPGRAM_API_KEY") or os.getenv("DEEPGRAM_API")
        if deepgram_key:
            return DeepgramSTTService(api_key=deepgram_key)

        # Fallback to Groq STT if available
        try:
            from pipecat.services.groq.stt import GroqSTTService
            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key:
                return GroqSTTService(api_key=groq_key)
        except ImportError:
            pass

        return DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY", "placeholder"))

    def build_tts_service(self) -> Any:
        """Resolve Text-to-Speech service."""
        if self.tts_service is not None:
            return self.tts_service

        if not PIPECAT_AVAILABLE:
            return None

        elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
        if elevenlabs_key:
            return ElevenLabsTTSService(
                api_key=elevenlabs_key,
                settings=ElevenLabsTTSService.Settings(
                    voice="pNInz6obpgDQGcFmaJgB",
                ),
            )

        # Deepgram TTS fallback
        try:
            from pipecat.services.deepgram.tts import DeepgramTTSService
            deepgram_key = os.getenv("DEEPGRAM_API_KEY") or os.getenv("DEEPGRAM_API")
            if deepgram_key:
                return DeepgramTTSService(api_key=deepgram_key)
        except ImportError:
            pass

        return ElevenLabsTTSService(
            api_key=os.getenv("ELEVENLABS_API_KEY", "placeholder"),
            settings=ElevenLabsTTSService.Settings(
                voice="pNInz6obpgDQGcFmaJgB",
            ),
        )

    async def run(self):
        """Main execution flow for the Pipecat voice bot (converted from run_bot)."""
        if not PIPECAT_AVAILABLE:
            raise RuntimeError(
                "Pipecat is not installed in the current environment. "
                "Install with: pip install \"pipecat-ai[daily,openai,deepgram,elevenlabs,silero]\""
            )

        if not self.transport:
            raise ValueError("A valid transport (Daily/WebRTC) must be provided to run().")

        logger.info("Starting Pipecat Voice Agent instance")

        stt = self.build_stt_service()
        tts = self.build_tts_service()
        llm = self.build_llm_service()

        self.context = LLMContext()
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            self.context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(),
            ),
        )

        normalizer = VoiceEntityTranscriptProcessor()
        ta = TalkingAnimation() if self.enable_animation and sprites else None

        pipeline_elements = [
            self.transport.input(),
            stt,
            normalizer,
            user_aggregator,
            llm,
            tts,
        ]
        if ta:
            pipeline_elements.append(ta)
        pipeline_elements.extend([
            self.transport.output(),
            assistant_aggregator,
        ])

        self.pipeline = Pipeline(pipeline_elements)

        self.worker = PipelineWorker(
            self.pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            idle_timeout_secs=getattr(self.runner_args, "pipeline_idle_timeout_secs", 60),
        )

        if self.enable_animation and quiet_frame:
            await self.worker.queue_frame(quiet_frame)

        self.runner = WorkerRunner(handle_sigint=getattr(self.runner_args, "handle_sigint", True))
        await self.runner.add_workers(self.worker)

        @self.worker.rtvi.event_handler("on_client_ready")
        async def on_client_ready(rtvi):
            logger.info("Pipecat RTVI client ready event received")
            if self.initial_greeting:
                self.context.add_message({"role": "developer", "content": self.initial_greeting})
                await self.worker.queue_frames([LLMRunFrame()])

        @self.transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Pipecat client connected")

        @self.transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("Pipecat client disconnected")
            if self.runner:
                await self.runner.cancel()

        await self.runner.run()

    def build_langchain_agent(self, thread_id: str, summary: Optional[str] = None):
        """Construct the tool-augmented LangChain agent with full system prompt & voice rules."""
        import httpx
        from app.services.agent_service import AgentService
        from app.services.prompt_service import PromptService
        from app.utils.tool import web_search, document_search, current_datetime, book_appointment, check_appointment
        from app.tools.preferences import save_preference
        from langchain.agents import create_agent
        from langgraph.checkpoint.memory import InMemorySaver
        from app.core.config import settings

        cfg = self.user_config or settings.public_llm_config()
        agent_svc = AgentService(client=httpx.AsyncClient(timeout=30.0), settings=settings)
        voice_model = agent_svc._get_llm_model(cfg)

        custom_behavior = (
            self.system_instruction or "AI voice assistant"
        )
        prompt_service = getattr(agent_svc, "prompt_service", None) or PromptService()
        base_voice_prompt = prompt_service.get_voice_system_prompt(behavior=custom_behavior)

        if summary and summary.strip():
            base_voice_prompt = (
                f"{base_voice_prompt}\n\n## Conversation Summary (Older turns):\n{summary.strip()[:4000]}"
            )

        voice_tools = [current_datetime, document_search, web_search, save_preference, book_appointment, check_appointment]

        voice_agent = create_agent(
            model=voice_model,
            tools=voice_tools,
            system_prompt=base_voice_prompt,
            checkpointer=InMemorySaver(),
        )
        return voice_agent, base_voice_prompt

    async def process_turn(
        self,
        audio_bytes: bytes,
        language: str = "en",
        session_id: Optional[str] = None,
        on_status: Optional[Any] = None,
        on_phrase: Optional[Any] = None,
        on_audio_chunk: Optional[Any] = None,
        on_user_transcript: Optional[Any] = None,
        is_interrupted: Optional[Any] = None,
        precomputed_transcript: str = "",
    ) -> Dict[str, Any]:
        """Process an audio turn through STT -> Entity Normalization -> Tool-Augmented LLM -> TTS."""
        from app.providers import stt as default_stt, tts as default_tts
        from app.core.context import (
            current_chatbot_id,
            current_user_id,
            current_llm_config,
            current_voice_session_id,
            current_search_attempts,
        )
        from app.utils.tool import reset_search_counter
        from langchain_core.messages import HumanMessage

        s_id = session_id or self.session_id or "turn_session"
        logger.info(f"[Pipecat Voice Flow] Processing turn for session {s_id}")

        # 1. Transcribe audio with confidence score & noise probability metadata
        stt_meta = {}
        if precomputed_transcript and precomputed_transcript.strip():
            raw_transcript = precomputed_transcript.strip()
            confidence = 0.95
            no_speech_prob = 0.0
            detected_lang = language or getattr(self, "language", "en") or "en"
        else:
            try:
                if hasattr(default_stt, "transcribe_detailed"):
                    stt_meta = await default_stt.transcribe_detailed(audio_bytes, "audio/wav", language=language)
                    raw_transcript = stt_meta.get("text", "")
                else:
                    raw_transcript = await default_stt.transcribe(audio_bytes, "audio/wav", language=language)
            except TypeError:
                raw_transcript = await default_stt.transcribe(audio_bytes, language=language)

            confidence = float(stt_meta.get("confidence", 0.85))
            no_speech_prob = float(stt_meta.get("no_speech_prob", 0.0))
            detected_lang = stt_meta.get("language") or language or getattr(self, "language", "en") or "en"

        detected_lang = str(detected_lang).split("-")[0].split("_")[0].lower()
        if any("\u0900" <= c <= "\u097f" for c in raw_transcript):
            detected_lang = "hi"
        self.language = detected_lang

        if not raw_transcript or not raw_transcript.strip():
            logger.info(f"[Pipecat Voice Flow] Empty transcription for session {s_id}")
            return {
                "transcript": "",
                "raw_transcript": "",
                "reply": "",
                "raw_reply": "",
                "audio_bytes": b"",
                "is_goodbye": False,
                "action": "ignore",
            }

        # 2. Deterministic Entity Normalization (Step 3)
        normalized_transcript = normalize_transcript_symbols(raw_transcript)
        logger.info(
            f"[Pipecat Voice Flow] Normalized transcript: '{normalized_transcript}' "
            f"(confidence={confidence}, no_speech_prob={no_speech_prob})"
        )

        # 3. Validation Tier 1: Pure noise / silence / Whisper hallucination / high no_speech_prob
        is_valid_speech = is_valid_speech_transcript(normalized_transcript)
        if not is_valid_speech or no_speech_prob > 0.60 or confidence < 0.35:
            logger.info(
                f"[STT Guard] Discarded unreliable input (confidence={confidence}, "
                f"no_speech_prob={no_speech_prob}, valid={is_valid_speech}): '{normalized_transcript}'"
            )
            return {
                "transcript": "",
                "raw_transcript": raw_transcript,
                "reply": "",
                "raw_reply": "",
                "audio_bytes": b"",
                "is_goodbye": False,
                "action": "ignore",
            }

        # Immediately notify client of user transcript so user bubble renders right away!
        if on_user_transcript and normalized_transcript:
            try:
                await on_user_transcript(normalized_transcript)
            except Exception as cb_err:
                logger.warning(f"Error in on_user_transcript callback: {cb_err}")

        # 4. Validation Tier 2: Borderline / Mumbled speech (ask user to repeat instead of triggering LLM)
        words = [w for w in normalized_transcript.split() if w.strip()]
        is_mumbled = (
            confidence < 0.55
            or (len(words) == 1 and len(words[0]) <= 2 and words[0].lower() not in {"hi", "no", "ok"})
            or "unintelligible" in normalized_transcript.lower()
            or "inaudible" in normalized_transcript.lower()
        )
        if is_mumbled:
            logger.info(
                f"[STT Guard] Unclear/mumbled speech detected (confidence={confidence}): '{normalized_transcript}'. "
                f"Prompting user to repeat without triggering LLM."
            )
            clarification_reply = (
                "माफ़ कीजिए, मैं समझ नहीं पाया। क्या आप दोबारा बोल सकते हैं?"
                if detected_lang == "hi"
                else "Sorry, I didn't quite catch that. Could you please repeat?"
            )
            clarification_audio = b""
            try:
                clarification_audio = await default_tts.synthesize(clarification_reply, language=detected_lang)
            except TypeError:
                clarification_audio = await default_tts.synthesize(clarification_reply)
            except Exception as tts_err:
                logger.warning(f"Error synthesizing repeat prompt: {tts_err}")

            return {
                "transcript": normalized_transcript,
                "raw_transcript": raw_transcript,
                "reply": clarification_reply,
                "raw_reply": clarification_reply,
                "audio_bytes": clarification_audio,
                "is_goodbye": False,
                "action": "ask_repeat",
                "language": detected_lang,
                "detected_language": detected_lang,
            }

        # 5. Set Context Tokens for Tool Execution
        current_chatbot_id.set(self.chatbot_id)
        if self.user_id:
            current_user_id.set(self.user_id)
        if self.user_config:
            current_llm_config.set(self.user_config)
        current_voice_session_id.set(s_id)
        current_search_attempts.set(0)
        reset_search_counter()

        # 4. Load Conversation Session Summary & Prior Turns for Context
        prior_messages = []
        session_summary = None
        try:
            from app.db.database import SessionLocal
            from app.core.session import get_session, history_limit
            from app.db.models import Message
            from sqlalchemy import select
            from langchain_core.messages import AIMessage

            async with SessionLocal() as db:
                s = await get_session(db, s_id)
                if s:
                    session_summary = getattr(s, "summary", None)
                    stmt = (
                        select(Message)
                        .where(
                            Message.session_id == s.id,
                            Message.summarized.is_(False),
                            Message.role.in_(("user", "assistant")),
                        )
                        .order_by(Message.id.desc())
                        .limit(history_limit())
                    )
                    recent_rows = list((await db.scalars(stmt)).all())
                    recent_rows.reverse()
                    for r in recent_rows:
                        if r.role == "user" and r.content:
                            prior_messages.append(HumanMessage(content=r.content))
                        elif r.role == "assistant" and r.content:
                            prior_messages.append(AIMessage(content=r.content))
        except Exception as db_hist_err:
            logger.warning(f"[Voice Flow] Could not load prior messages: {db_hist_err}")

        # 5. Run Tool-Augmented Agent with System Prompt & Voice Rules
        raw_reply = ""
        streamed_audio_chunks_count = 0
        try:
            voice_agent, _ = self.build_langchain_agent(thread_id=s_id, summary=session_summary)
            if on_status or on_audio_chunk:
                active_tool_depth = 0
                sentence_buffer = ""
                spoken_phrases: list[str] = []
                phrase_count = 0

                # Asynchronous queue for piping sentences to TTS worker concurrently
                phrase_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
                tts_worker_task: Optional[asyncio.Task] = None

                if on_audio_chunk:
                    async def _tts_consumer():
                        nonlocal streamed_audio_chunks_count
                        active_gen = None
                        try:
                            while True:
                                if is_interrupted and is_interrupted():
                                    break
                                try:
                                    phrase = await asyncio.wait_for(phrase_queue.get(), timeout=0.08)
                                except asyncio.TimeoutError:
                                    continue
                                if phrase is None:
                                    break
                                if is_interrupted and is_interrupted():
                                    break
                                cleaned_phrase = _spoken_text(phrase)
                                if not cleaned_phrase:
                                    continue
                                try:
                                    gen = default_tts.stream(cleaned_phrase, language=detected_lang)
                                except TypeError:
                                    gen = default_tts.stream(cleaned_phrase)
                                active_gen = gen
                                try:
                                    async for chunk in gen:
                                        if is_interrupted and is_interrupted():
                                            break
                                        if chunk.startswith(b"RIFF") and len(chunk) > 44:
                                            chunk = chunk[44:]
                                        if chunk:
                                            streamed_audio_chunks_count += 1
                                            await on_audio_chunk(chunk)
                                except Exception as tts_err:
                                    logger.warning(f"[TTS Stream] Streaming error for phrase '{cleaned_phrase}': {tts_err}")
                                finally:
                                    if hasattr(gen, "aclose"):
                                        await gen.aclose()
                                    active_gen = None
                        finally:
                            if active_gen and hasattr(active_gen, "aclose"):
                                try:
                                    await active_gen.aclose()
                                except Exception:
                                    pass

                    tts_worker_task = asyncio.create_task(_tts_consumer())

                user_content = normalized_transcript
                if detected_lang and detected_lang != "en":
                    lang_label = {
                        "hi": "Hindi",
                        "es": "Spanish",
                        "fr": "French",
                        "de": "German",
                        "zh": "Chinese",
                        "ja": "Japanese",
                        "ar": "Arabic",
                        "it": "Italian",
                        "pt": "Portuguese",
                        "ru": "Russian",
                    }.get(detected_lang, detected_lang.upper())
                    user_content = f"{normalized_transcript}\n[Language instruction: Spoken in {lang_label}. Reply naturally in {lang_label}.]"

                agent_messages = list(prior_messages)
                agent_messages.append(HumanMessage(content=user_content))

                async for event in voice_agent.astream_events(
                    {"messages": agent_messages},
                    {"configurable": {"thread_id": s_id}},
                    version="v2",
                ):
                    if is_interrupted and is_interrupted():
                        break

                    event_kind = event.get("event")
                    if event_kind == "on_tool_start":
                        active_tool_depth += 1
                        tool_name = event.get("name", "tool")
                        status_msg = (
                            "I am checking the current date and time..."
                            if tool_name == "current_datetime"
                            else (
                                "I am searching in the documents..."
                                if tool_name == "document_search"
                                else (
                                    "I am searching the web..."
                                    if tool_name == "web_search"
                                    else (
                                        "Processing appointment booking..."
                                        if tool_name == "book_appointment"
                                        else (
                                            "Checking appointment records..."
                                            if tool_name == "check_appointment"
                                            else f"Searching with {tool_name}..."
                                        )
                                    )
                                )
                            )
                        )
                        # Clear any preamble streamed before tool started
                        raw_reply = ""
                        if on_status:
                            await on_status("searching", status_msg, tool_name)
                    elif event_kind == "on_tool_end":
                        active_tool_depth = max(0, active_tool_depth - 1)
                        tool_name = event.get("name", "tool")
                        # Clear any tool-internal model tokens (e.g. query_rewriter) that streamed inside the tool
                        raw_reply = ""
                        if on_status:
                            await on_status("tool_completed", f"Finished {tool_name}", tool_name)
                    elif event_kind == "on_chat_model_end" and active_tool_depth == 0:
                        output = event.get("data", {}).get("output")
                        if output and hasattr(output, "content") and output.content and not raw_reply.strip():
                            raw_reply = str(output.content)
                    elif event_kind == "on_chat_model_stream":
                        # Only capture the final agent answer, ignore model calls executing inside tools
                        if active_tool_depth > 0:
                            continue
                        chunk = event.get("data", {}).get("chunk")
                        content = getattr(chunk, "content", None) if chunk else None
                        token = ""
                        if isinstance(content, str) and content:
                            token = content
                        elif isinstance(content, list):
                            token = "".join(
                                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                            )

                        if not token:
                            continue

                        raw_reply += token
                        if on_audio_chunk:
                            sentence_buffer += token
                            phrase, sentence_buffer = extract_phrase(sentence_buffer, is_first=(phrase_count == 0))
                            while phrase:
                                phrase_count += 1
                                spoken_phrases.append(phrase)
                                if on_phrase:
                                    running_text = " ".join(spoken_phrases).strip()
                                    await on_phrase(phrase, running_text)
                                phrase_queue.put_nowait(phrase)
                                phrase, sentence_buffer = extract_phrase(sentence_buffer, is_first=False)

                # Flush any remaining tokens in sentence_buffer
                if on_audio_chunk and sentence_buffer.strip() and not (is_interrupted and is_interrupted()):
                    remaining_phrase = sentence_buffer.strip()
                    spoken_phrases.append(remaining_phrase)
                    if on_phrase:
                        running_text = " ".join(spoken_phrases).strip()
                        await on_phrase(remaining_phrase, running_text)
                    phrase_queue.put_nowait(remaining_phrase)

                # Signal end of streaming to TTS worker
                if tts_worker_task:
                    phrase_queue.put_nowait(None)
                    if is_interrupted and is_interrupted():
                        tts_worker_task.cancel()
                    try:
                        await tts_worker_task
                    except (asyncio.CancelledError, Exception):
                        pass

                # If turn was interrupted during streaming, abort immediately without fallback
                if is_interrupted and is_interrupted():
                    logger.info(f"[Voice Flow] Turn cancelled by user barge-in for session {s_id}")
                    return {
                        "transcript": normalized_transcript,
                        "raw_transcript": raw_transcript,
                        "reply": "",
                        "raw_reply": "",
                        "audio_bytes": b"",
                        "streamed": True,
                        "action": "interrupted",
                        "language": detected_lang,
                        "detected_language": detected_lang,
                    }

                # Fallback if streaming ended without text
                if not raw_reply.strip():
                    try:
                        state = await voice_agent.aget_state({"configurable": {"thread_id": s_id}})
                        msgs = state.values.get("messages", [])
                        for m in reversed(msgs):
                            if getattr(m, "type", None) == "ai" and getattr(m, "content", None):
                                raw_reply = m.content
                                break
                    except Exception:
                        pass
            else:
                user_content = normalized_transcript
                if detected_lang and detected_lang != "en":
                    lang_label = {
                        "hi": "Hindi",
                        "es": "Spanish",
                        "fr": "French",
                        "de": "German",
                        "zh": "Chinese",
                        "ja": "Japanese",
                        "ar": "Arabic",
                        "it": "Italian",
                        "pt": "Portuguese",
                        "ru": "Russian",
                    }.get(detected_lang, detected_lang.upper())
                    user_content = f"{normalized_transcript}\n[Language instruction: Spoken in {lang_label}. Reply naturally in {lang_label}.]"

                agent_messages = list(prior_messages)
                agent_messages.append(HumanMessage(content=user_content))
                result = await voice_agent.ainvoke(
                    {"messages": agent_messages},
                    {"configurable": {"thread_id": s_id}},
                )
                result_messages = result.get("messages", [])
                for m in reversed(result_messages):
                    if getattr(m, "type", None) == "ai" and getattr(m, "content", None):
                        raw_reply = m.content
                        break
        except Exception as ag_err:
            logger.error(f"[Pipecat Voice Flow] Agent execution error: {ag_err}")
            raw_reply = "I apologize, but I encountered an issue while processing. Could you please repeat that?"

        # If turn was interrupted during processing, abort immediately
        if is_interrupted and is_interrupted():
            return {
                "transcript": normalized_transcript,
                "raw_transcript": raw_transcript,
                "reply": "",
                "raw_reply": "",
                "audio_bytes": b"",
                "streamed": True,
                "action": "interrupted",
                "language": detected_lang,
                "detected_language": detected_lang,
            }

        # 5. Spoken text cleaning (strips markdown, links, [END_CALL] tag for clean TTS audio)
        reply_text = _spoken_text(raw_reply)

        # 6. Synthesize speech (only if audio was not already streamed chunk-by-chunk and not interrupted)
        audio_out = b""
        if not (is_interrupted and is_interrupted()) and streamed_audio_chunks_count == 0 and reply_text and reply_text.strip():
            try:
                audio_out = await default_tts.synthesize(reply_text, language=detected_lang)
            except TypeError:
                audio_out = await default_tts.synthesize(reply_text)
            except Exception as tts_err:
                logger.error(f"[Pipecat Voice Flow] TTS synthesis error: {tts_err}")

        is_goodbye = _is_assistant_goodbye(raw_reply, user_transcript=normalized_transcript)

        return {
            "transcript": normalized_transcript,
            "raw_transcript": raw_transcript,
            "reply": reply_text,
            "raw_reply": raw_reply,
            "audio_bytes": audio_out,
            "streamed": streamed_audio_chunks_count > 0,
            "is_goodbye": is_goodbye,
            "language": detected_lang,
            "detected_language": detected_lang,
        }

    async def run_websocket_session(self, ws: Any, session_id: Optional[str] = None, initial_language: str = "en"):
        """Run an interactive streaming session over WebSocket using Pipecat flow logic."""
        from app.core.vad import Segmenter
        from app.core.audio_utils import pcm16_to_wav, suppress_noise_pcm16
        from app.db.database import SessionLocal
        from app.core.session import add_message, get_session
        from starlette.websockets import WebSocketState

        s_id = session_id or self.session_id or "default_voice_session"
        session_language = (initial_language or getattr(self, "language", "en") or "en").split("-")[0].split("_")[0].lower()
        self.language = session_language
        logger.info(f"[Pipecat WebSocket Flow] Starting session {s_id} (language: {session_language})")
        segmenter = Segmenter()
        turn_counter = 0

        is_connected = True
        disconnect_event = asyncio.Event()
        interrupted = False
        is_speaking = False
        is_processing = False
        current_active_turn_id: Optional[str] = None
        audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        active_turn_task: Optional[asyncio.Task] = None
        send_lock = asyncio.Lock()
        recent_assistant_text: list[str] = []

        async def cancel_active_turn() -> None:
            nonlocal active_turn_task, is_speaking, is_processing, interrupted, current_active_turn_id
            interrupted = True
            current_active_turn_id = None
            is_speaking = False
            is_processing = False
            if active_turn_task and not active_turn_task.done():
                active_turn_task.cancel()
                try:
                    await active_turn_task
                except (asyncio.CancelledError, Exception):
                    pass
            active_turn_task = None

        async def send_json(data: dict) -> bool:
            if not is_connected:
                return False
            try:
                if ws.client_state != WebSocketState.CONNECTED or ws.application_state != WebSocketState.CONNECTED:
                    return False
                await ws.send_text(json.dumps(data))
                return True
                async with send_lock:
                    if ws.client_state != WebSocketState.CONNECTED or ws.application_state != WebSocketState.CONNECTED:
                        return False
                    await ws.send_text(json.dumps(data))
                    return True
            except Exception:
                return False

        async def send_bytes(data: bytes) -> bool:
            if not is_connected:
                return False
            try:
                if ws.client_state != WebSocketState.CONNECTED or ws.application_state != WebSocketState.CONNECTED:
                    return False
                await ws.send_bytes(data)
                return True
                async with send_lock:
                    if ws.client_state != WebSocketState.CONNECTED or ws.application_state != WebSocketState.CONNECTED:
                        return False
                    await ws.send_bytes(data)
                    return True
            except Exception:
                return False

        # Send initial handshake frames expected by frontend and widget
        await send_json({
            "type": "session_created",
            "session_id": s_id,
            "engine": "pipecat",
            "language": session_language,
        })
        await send_json({
            "type": "audio_config",
            "output_sample_rate": 24000,
            "engine": "pipecat",
        })
        await send_json({
            "type": "ready",
            "session_id": s_id,
            "engine": "pipecat",
            "message": "Pipecat voice agent flow active",
        })
        await send_json({"type": "state", "state": "idle"})

        async def _handle_turn(payload: bytes, turn_id: str, precomputed_transcript: str = ""):
            nonlocal is_speaking, is_processing, interrupted, session_language, current_active_turn_id
            current_active_turn_id = turn_id
            is_processing = True
            await send_json({"type": "state", "state": "processing", "turn_id": turn_id})

            # Background heartbeat keeping connection active during long tool execution
            heartbeat_stop = asyncio.Event()

            async def _heartbeat_worker():
                while not heartbeat_stop.is_set() and is_connected:
                    try:
                        await asyncio.wait_for(heartbeat_stop.wait(), timeout=1.8)
                        break
                    except asyncio.TimeoutError:
                        await send_json({"type": "ping", "state": "processing", "turn_id": turn_id})

            hb_task = asyncio.create_task(_heartbeat_worker())

            async def _notify_tool_status(status_type: str, status_msg: str, tool_name: str):
                await send_json({
                    "type": "status",
                    "status": status_type,
                    "tool": tool_name,
                    "message": status_msg,
                    "turn_id": turn_id,
                })
                if status_type == "searching":
                    await send_json({
                        "type": "transcript",
                        "role": "assistant",
                        "text": status_msg,
                        "partial": True,
                        "turn_id": turn_id,
                        "is_status": True,
                    })
                    await send_json({"type": "state", "state": "speaking", "turn_id": turn_id})
                    await send_json({
                        "type": "audio_start",
                        "sample_rate": 24000,
                        "turn_id": turn_id,
                    })
                    # Stream small filler audio chunk (e.g. "I am searching in the documents...")
                    try:
                        raw_pcm = _FILLER_AUDIO_CACHE.get(status_msg)
                        if not raw_pcm:
                            from app.providers import tts as default_tts
                            filler_audio = await default_tts.synthesize(status_msg)
                            if filler_audio:
                                raw_pcm = filler_audio
                                if raw_pcm.startswith(b"RIFF") and len(raw_pcm) > 44:
                                    raw_pcm = raw_pcm[44:]
                                _FILLER_AUDIO_CACHE[status_msg] = raw_pcm

                        if raw_pcm:
                            chunk_size = 4096
                            for i in range(0, len(raw_pcm), chunk_size):
                                if interrupted or disconnect_event.is_set():
                                    break
                                chunk = raw_pcm[i:i + chunk_size]
                                sent = await send_bytes(chunk)
                                if not sent:
                                    break
                                await asyncio.sleep(0.015)
                    except Exception as filler_err:
                        logger.warning(f"Error streaming filler audio: {filler_err}")
                    await send_json({"type": "state", "state": "thinking", "turn_id": turn_id})

            async def _on_phrase_stream(phrase: str, running_text: str):
                if not is_connected or interrupted or turn_id != current_active_turn_id:
                    return
                await send_json({
                    "type": "transcript",
                    "role": "assistant",
                    "text": running_text,
                    "partial": True,
                    "turn_id": turn_id,
                })

            async def _on_audio_chunk_stream(chunk: bytes):
                nonlocal is_speaking
                if not is_connected or interrupted or turn_id != current_active_turn_id:
                    return
                if not is_speaking:
                    is_speaking = True
                    await send_json({"type": "state", "state": "speaking", "turn_id": turn_id})
                await send_bytes(chunk)

            user_transcript_sent = False

            async def _on_user_transcript_stream(text: str):
                nonlocal user_transcript_sent
                if not is_connected or interrupted or turn_id != current_active_turn_id or user_transcript_sent or not text or not text.strip():
                    return
                user_transcript_sent = True
                await send_json({
                    "type": "transcript",
                    "role": "user",
                    "text": text.strip(),
                    "turn_id": turn_id,
                })

            # Send audio_start right before turn execution so client is primed
            await send_json({
                "type": "audio_start",
                "sample_rate": 24000,
                "channels": 1,
                "format": "pcm_s16le",
                "turn_id": turn_id,
            })

            try:
                clean_pcm = suppress_noise_pcm16(payload)
                wav_bytes = pcm16_to_wav(clean_pcm)
                turn_result = await self.process_turn(
                    wav_bytes,
                    language=session_language,
                    session_id=s_id,
                    on_status=_notify_tool_status,
                    on_phrase=_on_phrase_stream,
                    on_audio_chunk=_on_audio_chunk_stream,
                    on_user_transcript=_on_user_transcript_stream,
                    is_interrupted=lambda: interrupted or not is_connected or turn_id != current_active_turn_id,
                    precomputed_transcript=precomputed_transcript,
                )
            except asyncio.CancelledError:
                logger.info(f"[Turn {turn_id}] Cancelled cleanly by user barge-in.")
                return
            except Exception as turn_err:
                logger.error(f"[Pipecat Voice Flow] Turn processing error: {turn_err}")
                turn_result = {
                    "transcript": "",
                    "reply": "I encountered an issue processing that. Could you repeat please?",
                    "audio_bytes": b"",
                    "streamed": False,
                    "action": "ignore",
                    "language": session_language,
                }
            finally:
                heartbeat_stop.set()
                hb_task.cancel()

            # Abort if interrupted while processing or a newer turn took over
            if interrupted or turn_id != current_active_turn_id or turn_result.get("action") == "interrupted":
                logger.info(f"[Turn {turn_id}] Discarded because turn was interrupted.")
                return

            # Dynamic Language State: Check if spoken language changed
            detected_lang = turn_result.get("detected_language") or turn_result.get("language")
            if detected_lang and detected_lang != session_language:
                logger.info(
                    f"[Language State] Detected language switch for session {s_id}: "
                    f"'{session_language}' -> '{detected_lang}'"
                )
                session_language = detected_lang
                self.language = detected_lang
                await send_json({
                    "type": "language_updated",
                    "language": session_language,
                    "turn_id": turn_id,
                })

            user_text = turn_result.get("transcript", "")
            bot_text = turn_result.get("reply", "")

            # Case 1: Unreliable / pure silence / noise -> Ignore completely (zero LLM calls)
            if turn_result.get("action") == "ignore" or not user_text or not user_text.strip():
                is_processing = False
                await send_json({"type": "state", "state": "idle", "turn_id": turn_id})
                return

            # Case 2: Borderline / Mumbled -> Prompt user to repeat without triggering LLM
            if turn_result.get("action") == "ask_repeat":
                await send_json({
                    "type": "transcript",
                    "role": "assistant",
                    "text": bot_text,
                    "turn_id": turn_id,
                })
                is_speaking = True
                await send_json({"type": "state", "state": "speaking", "turn_id": turn_id})
                audio_data = turn_result.get("audio_bytes")
                if audio_data:
                    raw_pcm = audio_data
                    if raw_pcm.startswith(b"RIFF") and len(raw_pcm) > 44:
                        raw_pcm = raw_pcm[44:]
                    chunk_size = 4096
                    for i in range(0, len(raw_pcm), chunk_size):
                        if interrupted or disconnect_event.is_set():
                            break
                        await send_bytes(raw_pcm[i:i + chunk_size])
                is_speaking = False
                is_processing = False
                await send_json({"type": "turn_end", "turn_id": turn_id})
                await send_json({"type": "state", "state": "idle", "turn_id": turn_id})
                return

            # Case 3: Reliable speech -> Normal LLM turn completion
            if not user_transcript_sent and user_text:
                await send_json({
                    "type": "transcript",
                    "role": "user",
                    "text": user_text,
                    "turn_id": turn_id,
                })

            # Save user message to DB asynchronously & trigger background summarization
            async def _save_turn(session_identifier: str, u_msg: str, a_msg: str, lang: str):
                try:
                    async with SessionLocal() as db:
                        s = await get_session(db, session_identifier)
                        if s:
                            if hasattr(s, "language") and s.language != lang:
                                s.language = lang
                            await add_message(db, session_id=s.id, role="user", content=u_msg)
                            await add_message(db, session_id=s.id, role="assistant", content=a_msg)
                            await db.commit()

                            # Compress conversation history into bounded summary if history overflows
                            from app.core.session import summarize_session_history
                            from app.providers import create_llm
                            from app.core.config import settings
                            try:
                                cfg = self.user_config or settings.public_llm_config()
                                llm_inst = create_llm(cfg)
                                asyncio.create_task(summarize_session_history(s.id, llm_inst))
                            except Exception as sum_err:
                                logger.warning(f"Error scheduling voice session summary: {sum_err}")
                except Exception as save_err:
                    logger.warning(f"Error persisting Pipecat turn messages: {save_err}")

            asyncio.create_task(_save_turn(s_id, user_text, bot_text, session_language))

            # Record assistant text for self-echo screening
            if bot_text:
                recent_assistant_text.append(bot_text)
                del recent_assistant_text[:-8]

            # If audio was not streamed (e.g. fallback occurred), send audio_bytes
            if not turn_result.get("streamed"):
                audio_data = turn_result.get("audio_bytes")
                if audio_data:
                    raw_pcm = audio_data
                    if raw_pcm.startswith(b"RIFF") and len(raw_pcm) > 44:
                        raw_pcm = raw_pcm[44:]
                    chunk_size = 4096
                    for i in range(0, len(raw_pcm), chunk_size):
                        if interrupted or disconnect_event.is_set():
                            break
                        await send_bytes(raw_pcm[i:i + chunk_size])

            # Send final non-partial transcript & end of turn
            await send_json({
                "type": "transcript",
                "role": "assistant",
                "text": bot_text,
                "partial": False,
                "turn_id": turn_id,
            })

            # Allow client jitter buffer playback to begin before concluding speaking state
            is_processing = False
            await asyncio.sleep(0.3)
            is_speaking = False
            await send_json({"type": "turn_end", "turn_id": turn_id})
            await send_json({"type": "state", "state": "idle", "turn_id": turn_id})

            if turn_result.get("is_goodbye"):
                await send_json({"type": "call_ended", "reason": "assistant_farewell"})

        async def _handle_greeting(text: str):
            nonlocal turn_counter, is_speaking, interrupted, current_active_turn_id
            interrupted = False
            greeting_clean = _spoken_text(text)
            turn_counter += 1
            greet_turn_id = f"greeting_{turn_counter}"
            current_active_turn_id = greet_turn_id
            recent_assistant_text.append(greeting_clean)
            del recent_assistant_text[:-8]

            await send_json({
                "type": "transcript",
                "role": "assistant",
                "text": greeting_clean,
                "turn_id": greet_turn_id,
            })
            is_speaking = True
            await send_json({"type": "state", "state": "speaking", "turn_id": greet_turn_id})
            await send_json({
                "type": "audio_start",
                "sample_rate": 24000,
                "turn_id": greet_turn_id,
            })
            from app.providers import tts as default_tts
            gen = default_tts.stream(greeting_clean)
            total_greeting_bytes = 0
            try:
                chunk_count = 0
                async for chunk in gen:
                    if interrupted or disconnect_event.is_set():
                        break
                    if chunk.startswith(b"RIFF") and len(chunk) > 44:
                        chunk = chunk[44:]
                    if chunk:
                        chunk_count += 1
                        total_greeting_bytes += len(chunk)
                        await send_bytes(chunk)

                if chunk_count == 0 and not interrupted and not disconnect_event.is_set():
                    greet_audio = await default_tts.synthesize(greeting_clean)
                    if greet_audio:
                        raw_pcm = greet_audio
                        if raw_pcm.startswith(b"RIFF") and len(raw_pcm) > 44:
                            raw_pcm = raw_pcm[44:]
                        chunk_size = 4096
                        for i in range(0, len(raw_pcm), chunk_size):
                            if interrupted or disconnect_event.is_set():
                                break
                            chunk = raw_pcm[i:i + chunk_size]
                            total_greeting_bytes += len(chunk)
                            await send_bytes(chunk)
            except Exception as greet_err:
                logger.warning(f"Error streaming greeting: {greet_err}")
            finally:
                if hasattr(gen, "aclose"):
                    await gen.aclose()
                # 24kHz 16-bit mono = 48,000 bytes per second
                play_duration = (total_greeting_bytes / 48000.0) if total_greeting_bytes > 0 else 0.5
                # Give browser time to finish playing greeting before resetting speaking state and echo window
                await asyncio.sleep(min(play_duration, 4.0))
                is_speaking = False
                await send_json({"type": "turn_end", "turn_id": greet_turn_id})
                await send_json({"type": "state", "state": "idle", "turn_id": greet_turn_id})

        async def receiver_loop():
            nonlocal is_connected, interrupted, is_speaking, active_turn_task, session_language
            try:
                while is_connected:
                    msg = await ws.receive()
                    msg_type = msg.get("type")
                    if msg_type == "websocket.disconnect":
                        is_connected = False
                        disconnect_event.set()
                        break

                    if "bytes" in msg and msg["bytes"]:
                        try:
                            audio_queue.put_nowait(msg["bytes"])
                        except asyncio.QueueFull:
                            try:
                                audio_queue.get_nowait()
                                audio_queue.put_nowait(msg["bytes"])
                            except Exception:
                                pass

                    elif "text" in msg and msg["text"]:
                        try:
                            data = json.loads(msg["text"])
                        except Exception:
                            data = {}

                        m_type = data.get("type")
                        if m_type == "hangup":
                            await cancel_active_turn()
                            await send_json({"type": "call_ended", "reason": "user_hangup"})
                            is_connected = False
                            disconnect_event.set()
                            break
                        elif m_type == "interrupt":
                            await cancel_active_turn()
                            await send_json({"type": "interrupt"})
                            await send_json({"type": "state", "state": "listening"})
                        elif m_type == "playback":
                            if data.get("state") == "end":
                                is_speaking = False
                            elif data.get("state") == "start":
                                is_speaking = True
                        elif m_type in ("config", "set_language"):
                            req_lang = data.get("language")
                            if req_lang:
                                session_language = req_lang.split("-")[0].split("_")[0].lower()
                                self.language = session_language
                            await send_json({"type": "config_ack", "language": session_language})
                        elif m_type == "greeting":
                            greeting_raw = data.get("text") or "Hello! How can I help you today?"
                            await cancel_active_turn()
                            active_turn_task = asyncio.create_task(_handle_greeting(greeting_raw))
            except Exception as rx_err:
                logger.warning(f"[Pipecat WebSocket Flow] Receiver note: {rx_err}")
            finally:
                is_connected = False
                disconnect_event.set()

        async def audio_worker():
            nonlocal turn_counter, interrupted, is_speaking, is_processing, active_turn_task, session_language
            from app.providers import stt as default_stt
            import time
            last_speaker_active_at = 0.0

            while is_connected and not disconnect_event.is_set():
                try:
                    pcm_chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    continue

                try:
                    speaker_on = is_speaking or is_processing
                    if speaker_on:
                        last_speaker_active_at = time.monotonic()

                    events = segmenter.feed(pcm_chunk, is_assistant_speaking=speaker_on)
                    for event, payload in events:
                        if event == "speech_start":
                            await send_json({"type": "speech_start"})
                            await send_json({"type": "state", "state": "listening"})
                            if is_speaking or is_processing:
                                # Soft duck audio while speech is detected; do NOT cancel yet (prevents echo aborts)
                                await send_json({"type": "duck_audio"})

                        elif event == "barge_in":
                            if is_speaking or is_processing:
                                logger.info("[VAD] Possible barge-in detected (soft ducking, waiting for utterance validation)")
                                await send_json({"type": "duck_audio"})

                        elif event == "utterance" and payload:
                            duration_ms = len(payload) * 1000 // 32000
                            speaker_on = is_speaking or is_processing
                            in_echo_window = speaker_on or (
                                last_speaker_active_at > 0 and (time.monotonic() - last_speaker_active_at < 1.8)
                            )

                            # Screen for echo ONLY while assistant is speaking or within short echo tail
                            if in_echo_window and recent_assistant_text:
                                quick_transcript = ""
                                try:
                                    wav_check = pcm16_to_wav(payload)
                                    quick_transcript = (
                                        await default_stt.transcribe(wav_check, "audio/wav", language=session_language)
                                    ).strip()
                                except Exception as stt_err:
                                    logger.warning(f"[Echo Guard] Quick STT check error: {stt_err}")

                                if not is_valid_speech_transcript(quick_transcript):
                                    logger.info(f"[Echo Guard] Discarded invalid transcript/noise: '{quick_transcript}' ({duration_ms}ms)")
                                    await send_json({"type": "unduck_audio"})
                                    await send_json({"type": "state", "state": "speaking" if is_speaking else "idle"})
                                    continue

                                if _is_echo_of(quick_transcript, recent_assistant_text):
                                    logger.info(f"[Echo Guard] Ignored echo of assistant's voice: '{quick_transcript}'")
                                    await send_json({"type": "unduck_audio"})
                                    await send_json({"type": "state", "state": "speaking" if is_speaking else "idle"})
                                    continue

                                # Genuine user barge-in confirmed by STT!
                                logger.info(f"[Barge-in] Genuine user speech confirmed by STT: '{quick_transcript}'")
                                await cancel_active_turn()
                                await send_json({"type": "interrupt"})
                                await send_json({"type": "unduck_audio"})

                                turn_counter += 1
                                turn_id = f"turn_{turn_counter}"
                                current_active_turn_id = turn_id
                                interrupted = False
                                active_turn_task = asyncio.create_task(
                                    _handle_turn(payload, turn_id, precomputed_transcript=quick_transcript)
                                )
                            else:
                                # Assistant is idle: normal user turn
                                turn_counter += 1
                                turn_id = f"turn_{turn_counter}"
                                current_active_turn_id = turn_id
                                interrupted = False
                                active_turn_task = asyncio.create_task(_handle_turn(payload, turn_id))

                except Exception as loop_err:
                    logger.exception(f"[Pipecat Voice Flow] Error in audio worker loop: {loop_err}")

        try:
            rx_task = asyncio.create_task(receiver_loop())
            worker_task = asyncio.create_task(audio_worker())

            await disconnect_event.wait()
            await cancel_active_turn()
            rx_task.cancel()
            worker_task.cancel()
        except Exception as exc:
            logger.error(f"[Pipecat WebSocket Flow] Error: {exc}")
        finally:
            logger.info(f"[Pipecat WebSocket Flow] Ended session {s_id}")


# ============================================================================
# Functional Wrappers for Compatibility
# ============================================================================

async def run_bot(
    transport: BaseTransport,
    runner_args: RunnerArguments,
    custom_llm: Optional[Any] = None,
    user_config: Optional[Dict[str, Any]] = None,
    system_instruction: Optional[str] = None,
    stt_service: Optional[Any] = None,
    tts_service: Optional[Any] = None,
    enable_animation: bool = True,
):
    """Main bot logic executing through the `PipecatVoiceAgent` class."""
    agent = PipecatVoiceAgent(
        transport=transport,
        runner_args=runner_args,
        custom_llm=custom_llm,
        user_config=user_config,
        system_instruction=system_instruction,
        stt_service=stt_service,
        tts_service=tts_service,
        enable_animation=enable_animation,
    )
    await agent.run()


async def bot(
    runner_args: RunnerArguments,
    custom_llm: Optional[Any] = None,
    user_config: Optional[Dict[str, Any]] = None,
):
    """Main bot entry point matching the Pipecat runner utility."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(
        transport=transport,
        runner_args=runner_args,
        custom_llm=custom_llm,
        user_config=user_config,
    )


if __name__ == "__main__":
    if PIPECAT_AVAILABLE:
        from pipecat.runner.run import main
        main()
    else:
        print("Pipecat not installed. Please install pipecat-ai.")
