"""Groq Whisper speech-to-text adapter."""

from __future__ import annotations

import httpx

from app.core.config import Settings, settings


class GroqSTT:
    """Transcribe supported audio formats with Groq's transcription API."""

    endpoint = "https://api.groq.com/openai/v1/audio/transcriptions"
    extensions = {
        "audio/flac": "flac",
        "audio/mp3": "mp3",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
        "audio/ogg": "ogg",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/webm": "webm",
        "video/webm": "webm",
        "video/mp4": "mp4",
    }

    def __init__(self, config: Settings = settings, client: httpx.AsyncClient | None = None):
        self.config = config
        self._client: httpx.AsyncClient | None = client

    def _get_client(self) -> httpx.AsyncClient:
        """Reuse a warm, persistent HTTP client with connection pooling to eliminate TLS handshake latency."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(45.0, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=60.0),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the persistent connection pool cleanly."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def transcribe(
        self, audio: bytes, mime: str, language: str | None = None
    ) -> str:
        """Transcribe audio and return plain text (backwards compatible)."""
        result = await self.transcribe_detailed(audio, mime, language=language)
        return result.get("text", "")

    async def transcribe_detailed(
        self, audio: bytes, mime: str, language: str | None = None
    ) -> dict:
        """Transcribe audio with confidence score and no_speech probability metadata."""
        if not audio:
            raise ValueError("Audio payload cannot be empty.")
        if not self.config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        if not self.config.STT_MODEL:
            raise RuntimeError("STT_MODEL is not configured.")

        normalized_mime = mime.split(";", maxsplit=1)[0].strip().lower()
        extension = self.extensions.get(normalized_mime)
        if extension is None:
            raise ValueError(f"Unsupported audio MIME type: {normalized_mime or '(empty)'}")

        data = {"model": self.config.STT_MODEL, "response_format": "verbose_json"}
        if language:
            data["language"] = language

        client = self._get_client()
        try:
            response = await client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.config.GROQ_API_KEY}"},
                data=data,
                files={"file": (f"audio.{extension}", audio, normalized_mime)},
            )
            response.raise_for_status()
            resp_data = response.json()
        except Exception:
            # Fallback to standard json format if verbose_json fails
            data["response_format"] = "json"
            response = await client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.config.GROQ_API_KEY}"},
                data=data,
                files={"file": (f"audio.{extension}", audio, normalized_mime)},
            )
            response.raise_for_status()
            resp_data = response.json()

        text = resp_data.get("text", "")
        if not isinstance(text, str):
            raise RuntimeError("Groq returned an invalid transcription response.")
        text = text.strip()

        # Compute confidence and no_speech probability from segment logprobs
        segments = resp_data.get("segments", [])
        confidence = 0.88
        no_speech_prob = 0.0

        if segments and isinstance(segments, list):
            no_speech_probs = [float(s.get("no_speech_prob", 0.0)) for s in segments if isinstance(s, dict)]
            avg_logprobs = [float(s.get("avg_logprob", -0.4)) for s in segments if isinstance(s, dict)]
            no_speech_prob = max(no_speech_probs) if no_speech_probs else 0.0
            mean_logprob = sum(avg_logprobs) / len(avg_logprobs) if avg_logprobs else -0.4

            import math
            prob = math.exp(max(-5.0, min(0.0, mean_logprob)))
            confidence = round(prob * max(0.0, 1.0 - no_speech_prob), 3)

        return {
            "text": text,
            "confidence": confidence,
            "no_speech_prob": round(no_speech_prob, 3),
            "language": resp_data.get("language", language or "en"),
            "duration": resp_data.get("duration", 0.0),
        }
