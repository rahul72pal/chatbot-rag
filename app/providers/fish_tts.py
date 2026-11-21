"""Fish Audio (Fish AI) Text-to-Speech (TTS) provider adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
import os

import httpx

from app.core.config import Settings, settings
from app.core.logger import logger


class FishTTS:
    """Stream and synthesize voice using Fish Audio API."""

    BASE_URL = "https://api.fish.audio/v1/tts"

    def __init__(
        self,
        config: Settings = settings,
        model: str | None = None,
        reference_id: str | None = None,
        sample_rate: int = 24000,
    ):
        self.config = config
        self._api_key = (
            getattr(config, "FISH_AUDIO_API_KEY", "")
            or os.getenv("FISH_AUDIO_API_KEY", "")
        )
        self.model = (
            model
            or getattr(config, "FISH_AUDIO_MODEL", None)
            or os.getenv("FISH_AUDIO_MODEL", "s2.1-pro-free")
        )
        self.reference_id = (
            reference_id
            or getattr(config, "FISH_AUDIO_REFERENCE_ID", None)
            or os.getenv("FISH_AUDIO_REFERENCE_ID", "ca3007f96ae7499ab87d27ea3599956a")
        )
        self.sample_rate = sample_rate
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                http2=False,
                timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0),
                limits=httpx.Limits(max_keepalive_connections=0, max_connections=20),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "model": self.model,
            "Connection": "close",
        }

    def _payload(self, text: str) -> dict[str, Any]:
        return {
            "text": text.strip(),
            "reference_id": self.reference_id,
            "format": "pcm",
            "sample_rate": self.sample_rate,
        }

    async def stream(self, text: str, language: str = "en") -> AsyncIterator[bytes]:
        """Stream real-time 24kHz linear16 PCM chunks for seamless WebSocket playback."""
        if not text or not text.strip():
            return

        if not self._api_key:
            logger.error("[Fish TTS] API key missing (FISH_AUDIO_API_KEY)")
            return

        client = self._get_client()
        try:
            async with client.stream(
                "POST",
                self.BASE_URL,
                headers=self._headers(),
                json=self._payload(text),
            ) as response:
                if response.status_code != 200:
                    err_bytes = await response.aread()
                    logger.error(
                        f"[Fish TTS] HTTP {response.status_code}: "
                        f"{err_bytes.decode(errors='replace')}"
                    )
                    return

                logger.info(
                    f"[Fish TTS] Model: {self.model} | Voice: {self.reference_id} | "
                    f"Content-Type: {response.headers.get('content-type')}"
                )

                async for chunk in response.aiter_bytes(chunk_size=4096):
                    if chunk.startswith(b"RIFF") and len(chunk) > 44:
                        chunk = chunk[44:]
                    if chunk:
                        yield chunk

        except httpx.TimeoutException:
            logger.exception("[Fish TTS] Request timed out")
            await self.aclose()
        except Exception:
            logger.exception("[Fish TTS] Streaming failed")
            await self.aclose()

    async def synthesize(self, text: str, language: str = "en") -> bytes:
        """Synthesize text into a complete 24kHz linear16 PCM audio payload."""
        if not text or not text.strip():
            return b""

        chunks: list[bytes] = []
        async for chunk in self.stream(text, language=language):
            chunks.append(chunk)

        return b"".join(chunks)
