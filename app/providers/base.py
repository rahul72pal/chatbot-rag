"""Provider-neutral contracts for the voice pipeline.

Concrete speech providers can implement these protocols without coupling the
voice orchestration layer to a vendor SDK. The LLM implementation should be
constructed from the authenticated user's existing LLM configuration and use
its ``voice_agent_model`` selection.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol


Message = dict[str, Any]
Tool = dict[str, Any]


class STT(Protocol):
    """Speech-to-text provider contract."""

    async def transcribe(
        self, audio: bytes, mime: str, language: str | None = None
    ) -> str:
        """Convert an audio payload to text."""
        ...


class LLM(Protocol):
    """Language model contract used by voice turns."""

    async def chat(
        self, messages: Sequence[Message], tools: Sequence[Tool] | None = None
    ) -> Message:
        """Return one assistant response for the supplied conversation."""
        ...

    def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Stream assistant text chunks for the supplied conversation."""
        ...


class TTS(Protocol):
    """Text-to-speech provider contract."""

    async def synthesize(self, text: str) -> bytes:
        """Convert text to one audio payload."""
        ...

    def stream(self, text: str) -> AsyncIterator[bytes]:
        """Stream audio chunks for the supplied text."""
        ...
