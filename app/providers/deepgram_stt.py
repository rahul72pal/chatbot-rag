"""Deepgram Speech-to-Text (STT) provider adapter."""

from __future__ import annotations

import httpx

from app.core.config import Settings, settings
from app.core.logger import logger


class DeepgramSTT:
    """Transcribe audio using Deepgram's Nova-3 / Nova-2 STT REST API."""

    ENDPOINT = "https://api.deepgram.com/v1/listen"

    def __init__(
        self,
        config: Settings = settings,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.config = config
        self._api_key = config.DEEPGRAM_API or getattr(config, "DEEPGRAM_API_KEY", "")
        self.model = (
            model
            or getattr(config, "DEEPGRAM_STT_MODEL", None)
            or "nova-3"
        )
        self._client: httpx.AsyncClient | None = client

    def _get_client(self) -> httpx.AsyncClient:
        """Create an HTTP client configured for clean, reliable audio uploads without stale socket reuse."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                http2=False,
                timeout=httpx.Timeout(connect=5.0, read=25.0, write=25.0, pool=5.0),
                limits=httpx.Limits(max_keepalive_connections=0, max_connections=20),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the connection pool cleanly."""
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def transcribe(
        self, audio: bytes, mime: str = "audio/wav", language: str | None = None
    ) -> str:
        """Transcribe audio and return plain text (backwards compatible)."""
        result = await self.transcribe_detailed(audio, mime, language=language)
        return result.get("text", "")

    async def transcribe_detailed(
        self, audio: bytes, mime: str = "audio/wav", language: str | None = None
    ) -> dict:
        """Transcribe audio with confidence score and no_speech probability metadata."""
        if not audio:
            raise ValueError("Audio payload cannot be empty.")
        if not self._api_key:
            raise RuntimeError("DEEPGRAM_API key is not configured.")

        normalized_mime = mime.split(";", maxsplit=1)[0].strip().lower() or "audio/wav"

        params: dict[str, str] = {
            "model": self.model,
            "smart_format": "true",
            "punctuate": "true",
        }
        # Deepgram Nova-3 detects multilingual speech dynamically
        if language and language.lower() not in {"auto", "detect"}:
            params["language"] = language
        else:
            params["detect_language"] = "true"

        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": normalized_mime,
            "Content-Length": str(len(audio)),
            "Connection": "close",
        }

        resp_data = None
        for attempt in range(2):
            client = self._get_client()
            try:
                response = await client.post(
                    self.ENDPOINT,
                    headers=headers,
                    params=params,
                    content=audio,
                )
                if response.status_code == 408 and attempt == 0:
                    logger.warning("[Deepgram STT] Received 408 SLOW_UPLOAD, retrying on a fresh connection...")
                    await self.aclose()
                    import asyncio
                    await asyncio.sleep(0.15)
                    continue

                if response.status_code != 200:
                    err_text = response.text
                    logger.error(f"[Deepgram STT] HTTP {response.status_code}: {err_text}")
                    response.raise_for_status()

                resp_data = response.json()
                break
            except (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError, httpx.WriteTimeout) as net_err:
                await self.aclose()
                if attempt == 0:
                    logger.warning(f"[Deepgram STT] Transient network disconnect ({net_err}), retrying on fresh connection...")
                    import asyncio
                    await asyncio.sleep(0.15)
                    continue
                logger.error(f"[Deepgram STT] Request failed after retry: {net_err}")
                raise
            except Exception as exc:
                await self.aclose()
                logger.exception(f"[Deepgram STT] Connection or parsing error: {exc}")
                raise

        # Parse Deepgram transcription results
        channels = resp_data.get("results", {}).get("channels", [])
        if not channels or not isinstance(channels, list):
            return {
                "text": "",
                "confidence": 0.0,
                "no_speech_prob": 1.0,
                "language": language or "en",
            }

        alternatives = channels[0].get("alternatives", [])
        if not alternatives or not isinstance(alternatives, list):
            return {
                "text": "",
                "confidence": 0.0,
                "no_speech_prob": 1.0,
                "language": language or "en",
            }

        primary_alt = alternatives[0]
        text = primary_alt.get("transcript", "").strip()
        confidence = float(primary_alt.get("confidence", 0.85))

        if not text:
            confidence = 0.0
            no_speech_prob = 1.0
        else:
            no_speech_prob = round(max(0.0, 1.0 - confidence), 3)

        detected_lang = (
            channels[0].get("detected_language")
            or primary_alt.get("detected_language")
            or primary_alt.get("language")
        )
        if not detected_lang and language and language.lower() not in {"auto", "detect"}:
            detected_lang = language

        # Multi-lingual script detection on transcript
        if any("\u0900" <= c <= "\u097f" for c in text):
            detected_lang = "hi"
        elif any("\u4e00" <= c <= "\u9fff" for c in text):
            detected_lang = "zh"
        elif any("\u3040" <= c <= "\u30ff" for c in text):
            detected_lang = "ja"
        elif any("\u0600" <= c <= "\u06ff" for c in text):
            detected_lang = "ar"
        elif any("\u0400" <= c <= "\u04ff" for c in text):
            detected_lang = "ru"

        if not detected_lang:
            detected_lang = "en"

        # Normalize language code e.g. "en-US" -> "en", "hi-IN" -> "hi"
        normalized_lang = str(detected_lang).split("-")[0].split("_")[0].lower()

        return {
            "text": text,
            "confidence": round(confidence, 3),
            "no_speech_prob": no_speech_prob,
            "language": normalized_lang,
        }
