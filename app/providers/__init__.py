"""Concrete voice provider factory.

STT and TTS use environment-configured provider settings.
TTS provider is selected via the TTS_PROVIDER setting (google | deepgram).
The conversational LLM is built per caller: an authenticated owner's saved
configuration when present, otherwise the server-owned public model.
"""

from typing import Any

from app.core.config import Settings, settings
from app.core.logger import logger
from app.providers.base import LLM, Message, STT, TTS, Tool
from app.providers.user_llm import UserConfigLLM


def _build_stt(config: Settings) -> STT:
    """Select the STT provider based on STT_PROVIDER env var (deepgram | groq)."""
    provider = (getattr(config, "STT_PROVIDER", None) or "deepgram").strip().lower()

    if provider == "groq":
        from app.providers.groq_stt import GroqSTT
        logger.info("[STT] Using Groq STT provider")
        return GroqSTT(config)
    else:
        # Default: Deepgram STT (nova-3)
        from app.providers.deepgram_stt import DeepgramSTT
        logger.info("[STT] Using Deepgram STT provider")
        return DeepgramSTT(config)


stt: STT = _build_stt(settings)


def _build_tts(config: Settings) -> TTS:
    """Select the TTS provider based on TTS_PROVIDER env var (fish | deepgram)."""
    provider = (config.TTS_PROVIDER or "fish").strip().lower()

    if provider == "deepgram":
        from app.providers.deepgram_tts import DeepgramTTS
        logger.info("[TTS] Using Deepgram TTS provider")
        return DeepgramTTS(config)
    else:
        # Default: Fish Audio TTS (s2.1-pro-free)
        from app.providers.fish_tts import FishTTS
        logger.info("[TTS] Using Fish Audio TTS provider")
        return FishTTS(config)


tts: TTS = _build_tts(settings)


def create_stt(config: Settings = settings) -> STT:
    """Create a fresh STT provider instance (e.g. per voice session)."""
    return _build_stt(config)


def create_tts(config: Settings = settings) -> TTS:
    """Create a fresh TTS provider instance (e.g. per voice session)."""
    return _build_tts(config)


def create_llm(agent_service: Any, user_config: dict[str, Any]) -> LLM:
    """Build an LLM adapter from a resolved user LLM config document."""
    return UserConfigLLM(agent_service, user_config)


__all__ = ["LLM", "Message", "STT", "TTS", "Tool", "stt", "tts", "create_stt", "create_tts", "create_llm"]
