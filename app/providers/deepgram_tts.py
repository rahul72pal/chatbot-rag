from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.core.config import Settings, settings
from app.core.logger import logger


class DeepgramTTS:

    BASE_URL = "https://api.deepgram.com/v1/speak"

    def __init__(
        self,
        config: Settings = settings,
        model: str = "aura-2-thalia-en",
        speed: float = 1.0,
    ):
        self.config = config
        self._api_key = config.DEEPGRAM_API
        self.model = model
        self.speed = speed
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                http2=False,
                timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=30.0),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the persistent connection pool cleanly."""
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    def _headers(self):
        return {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "application/json",
        }

    def _params(self):
        return {
            "model": self.model,
            "encoding": "linear16",
            "sample_rate": 24000,
            "container": "none",
            "speed": self.speed,
        }

    async def stream(self, text: str, language: str = "en") -> AsyncIterator[bytes]:

        if not text or not text.strip():
            return

        if not self._api_key:
            logger.error("[Deepgram TTS] API key missing")
            return

        try:
            client = self._get_client()
            async with client.stream(
                "POST",
                self.BASE_URL,
                headers=self._headers(),
                params=self._params(),
                json={"text": text.strip()},
            ) as response:

                if response.status_code != 200:
                    error = await response.aread()
                    logger.error(
                        f"[Deepgram TTS] HTTP {response.status_code}: "
                        f"{error.decode(errors='replace')}"
                    )
                    return

                logger.info(
                    f"[Deepgram TTS] Model: "
                    f"{response.headers.get('dg-model-name', self.model)} | "
                    f"Content-Type: {response.headers.get('content-type')}"
                )

                async for chunk in response.aiter_bytes(
                    chunk_size=4096
                ):
                    if chunk:
                        yield chunk

        except httpx.TimeoutException:
            logger.exception("[Deepgram TTS] Request timed out")
            await self.aclose()

        except Exception:
            logger.exception("[Deepgram TTS] Streaming failed")
            await self.aclose()

    async def synthesize(self, text: str, language: str = "en") -> bytes:

        if not text or not text.strip():
            return b""

        chunks = []

        async for chunk in self.stream(text, language=language):
            chunks.append(chunk)

        return b"".join(chunks)
